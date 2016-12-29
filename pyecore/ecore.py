from ordered_set import OrderedSet
import sys
from inspect import getmembers, isclass


nsPrefix = 'ecore'
nsURI = 'http://www.eclipse.org/emf/2002/Ecore'


def getEClassifier(name, searchspace=None):
    searchspace = searchspace if searchspace else eClassifiers
    try:
        return searchspace[name]
    except KeyError:
        return None


class BadValueError(TypeError):
    def __init__(self, got=None, expected=None):
        msg = "Expected type {0}, but got type {1} with value {2} instead"
        msg = msg.format(expected, type(got).__name__, got)
        super().__init__(msg)


class EcoreUtils(object):
    def isinstance(obj, _type):
        if obj is None:
            return True
        elif isinstance(_type, EEnum):
            return obj in _type
        elif isinstance(_type, EDataType) or isinstance(_type, EAttribute):
            return isinstance(obj, _type.eType)
        elif isinstance(_type, EClass):
            if isinstance(obj, EObject):
                return obj.eClass is _type \
                       or _type in obj.eClass.eAllSuperTypes()
            return False
        return isinstance(obj, _type)

    def getRoot(obj):
        if not obj:
            return None
        previous = obj
        while previous.eContainer() is not None:
            previous = previous.eContainer()
        return previous


class Core(object):
    def getattr(self, name):
        ex = None
        try:
            return object.__getattribute__(self, name)
        except AttributeError as e:
            ex = e
        feature = self.eClass.findEStructuralFeature(name)
        if not feature:
            raise ex

        if feature.many:
            new_list = ECollection.create(self, feature)
            self.__setattr__(name, new_list)
            return new_list
        else:
            default_value = None
            if hasattr(feature.eType, 'default_value'):
                default_value = feature.eType.default_value
            if hasattr(feature, 'default_value'):
                default_value = feature.default_value
            self.__setattr__(name, default_value)
            return default_value

    def setattr(self, name, value):
        feat = self.eClass.findEStructuralFeature(name)
        if not feat:
            object.__setattr__(self, name, value)
            return

        if feat.many and not isinstance(value, ECollection):
            raise BadValueError(got=value, expected=feat.eType)
        elif not feat.many and not EcoreUtils.isinstance(value, feat.eType):
            raise BadValueError(got=value, expected=feat.eType)

        try:
            previous_value = object.__getattribute__(self, feat.name)
        except AttributeError:
            previous_value = None

        if isinstance(feat.eType, EDataType) and isinstance(value, str):
            object.__setattr__(self, name, feat.eType.from_string(value))
        else:
            object.__setattr__(self, name, value)
        if self._isready:
            self._isset.append(name)
        if self._isready and isinstance(feat, EReference):
            if feat.containment and isinstance(value, EObject):
                value._container = self
                value._containment_feature = feat
            elif feat.containment and not value and previous_value:
                previous_value._container = None
                previous_value._containment_feature = None
            if feat.eOpposite and isinstance(value, EObject):
                eOpposite = feat.eOpposite
                if eOpposite.many:
                    value.__getattribute__(eOpposite.name)  # force resolve
                    object.__getattribute__(value, eOpposite.name).append(self)
                else:
                    object.__setattr__(value, eOpposite.name, self)
            elif feat.eOpposite and value is None:
                eOpposite = feat.eOpposite
                if previous_value and eOpposite.many:
                    object.__getattribute__(previous_value, eOpposite.name) \
                          .remove(self)
                elif previous_value:
                    object.__setattr__(previous_value, eOpposite.name, None)

    def _promote(cls, abstract=False):
        cls.eClass = EClass(cls.__name__)
        cls.eClass.abstract = abstract
        cls._staticEClass = True
        # init super types
        for _cls in cls.__bases__:
            if _cls is not EObject:
                cls.eClass.eSuperTypes.append(_cls.eClass)
        # init eclass by reflection
        for k, v in cls.__dict__.items():
            if isinstance(v, EStructuralFeature):
                if not v.name:
                    v.name = k
                cls.eClass.eStructuralFeatures.append(v)

    def compute_eclass(module_name):
        module = sys.modules[module_name]

        def is_valid_eclass(_class):
            return isclass(_class) and _class.__module__ is module_name
        return {k: v for k, v in getmembers(module, is_valid_eclass)}


class EObject(object):
    def __init__(self):
        self.__initmetattr__()
        self.__subinit__()

    def __subinit__(self):
        self._xmiid = None
        self._isset = []
        self._container = None
        self._isready = False
        self._containment_feature = None

    def __initmetattr__(self, _super=None):
        _super = _super if _super else self.__class__
        if _super is EObject:
            return
        for key, value in _super.__dict__.items():
            if isinstance(value, EAttribute):
                object.__setattr__(self, key, value)
            elif isinstance(value, EReference):
                if value.many:
                    object.__setattr__(self,
                                       key,
                                       ECollection.create(self, value))
                else:
                    object.__setattr__(self, key, None)
        for super_class in _super.__bases__:
            super_class.__initmetattr__(self, super_class)

    def eContainer(self):
        return self._container

    def eContainmentFeature(self):
        return self._containment_feature


class ECollection(object):
    def create(owner, feature):
        if feature.ordered and feature.unique:
            return EOrderedSet(owner, efeature=feature)
        elif feature.ordered and not feature.unique:
            return EList(owner, efeature=feature)
        elif feature.unique:
            return ESet(owner, efeature=feature)
        else:
            return EList(owner, efeature=feature)  # see for better implem

    def __init__(self, owner, efeature=None):
        self._owner = owner
        self._efeature = efeature

    def check(self, value):
        if not EcoreUtils.isinstance(value, self._efeature.eType):
            raise BadValueError(value, self._efeature.eType)

    def _update_container(self, value, previous_value=None):
        if not isinstance(self._efeature, EReference):
            return
        if self._efeature.containment and not previous_value:
            value._container = self._owner
            value._containment_feature = self._efeature
        elif self._efeature.containment and previous_value:
            previous_value._container = value
            previous_value._containment_feature = value

    def _update_opposite(self, owner, new_value, remove=False):
        if not isinstance(self._efeature, EReference):
            return
        eOpposite = self._efeature.eOpposite
        if eOpposite:
            if eOpposite.many and not remove:
                owner.__getattribute__(eOpposite.name)  # force resolve
                object.__getattribute__(owner, eOpposite.name) \
                      .append(new_value, False)
            elif eOpposite.many and remove:
                object.__getattribute__(owner, eOpposite.name) \
                      .remove(new_value, False)
            else:
                object.__setattr__(owner, eOpposite.name,
                                   None if remove else new_value)

    def remove(self, value, update_opposite=True):
        if update_opposite:
            self._update_container(None, previous_value=value)
            self._update_opposite(value, self._owner, remove=True)
        super().remove(value)

    def select(self, f):
        return [x for x in self if f(x)]

    def reject(self, f):
        return [x for x in self if not f(x)]


class EList(ECollection, list):
    def __init__(self, owner, efeature=None):
        super().__init__(owner, efeature)

    def append(self, value, update_opposite=True):
        self.check(value)
        if update_opposite:
            self._update_container(value)
            self._update_opposite(value, self._owner)
        super().append(value)

    def extend(self, sublist):
        all(self.check(x) for x in sublist)
        for x in sublist:
            self._update_container(x)
            self._update_opposite(x, self._owner)
        super().extend(sublist)

    # for Python2 compatibility, in Python3, __setslice__ is deprecated
    def __setslice__(self, i, j, y):
        all(self.check(x) for x in y)
        super().__setslice__(i, j, y)

    def __setitem__(self, i, y):
        self.check(y)
        self._update_container(y)
        self._update_opposite(y, self._owner)
        super().__setitem__(i, y)


class EAbstractSet(ECollection):
    def __init__(self, owner, efeature=None):
        super().__init__(owner, efeature)

    def append(self, value, update_opposite=True):
        self.add(value, update_opposite)

    def add(self, value, update_opposite=True):
        self.check(value)
        if update_opposite:
            self._update_container(value)
            self._update_opposite(value, self._owner)
        super().add(value)

    def extend(self, sublist):
        self.update(*sublist)

    def update(self, *others):
        all(self.check(x) for x in others)
        for x in others:
            self._update_container(x)
            self._update_opposite(x, self._owner)
        super().update(others)


class ESet(EAbstractSet, set):
    def __init__(self, owner, efeature=None):
        super().__init__(owner, efeature)


class EOrderedSet(EAbstractSet, OrderedSet):
    def __init__(self, owner, efeature=None):
        super().__init__(owner, efeature)
        OrderedSet.__init__(self)


class EModelElement(EObject):
    def __init__(self):
        super().__init__()


class EAnnotation(EModelElement):
    def __init__(self, source=None):
        super().__init__()
        self.source = source
        self.details = {}


class ENamedElement(EModelElement):
    def __init__(self, name=None):
        super().__init__()
        self.name = name


class EPackage(ENamedElement):
    def __init__(self, name=None, nsURI=None, nsPrefix=None):
        super().__init__(name)
        self.nsURI = nsURI
        self.nsPrefix = nsPrefix

    def getEClassifier(self, name):
        return next((c for c in self.eClassifiers if c.name == name), None)


class ETypedElement(ENamedElement):
    def __init__(self, name=None, eType=None, ordered=True, unique=True,
                 lower=0, upper=1, required=False):
        super().__init__(name)
        self.eType = eType
        self.lowerBound = int(lower)
        self.upperBound = int(upper)
        self.ordered = ordered
        self.unique = unique
        self.required = required

    # @property
    # def upper(self):
    #     return self.upperBound
    #
    # @upper.setter
    # def upper(self, value):
    #     self.upperBound = value
    #
    # @property
    # def lower(self):
    #     return self.lowerBound
    #
    # @lower.setter
    # def lower(self, value):
    #     self.lowerBound = value

    @property
    def many(self):
        return int(self.upperBound) > 1 or int(self.upperBound) < 0


class EOperation(ETypedElement):
    def __init__(self, name=None, eType=None, params=None, exceptions=None):
        super().__init__(name, eType)
        if params:
            for param in params:
                self.eParameters.append(param)
        if exceptions:
            for exception in exceptions:
                self.eExceptions.append(exception)


class ETypeParameter(ENamedElement):
    def __init__(self, name=None):
        super().__init__(name)


class EGenericType(EObject):
    def __init__(self):
        super().__init__()


class EParameter(ETypedElement):
    def __init__(self, name=None, eType=None):
        super().__init__(name, eType)


class EClassifier(ENamedElement):
    def __init__(self, name=None):
        super().__init__(name)


class EDataType(EClassifier):
    def __init__(self, name=None, eType=None, default_value=None,
                 from_string=None):
        super().__init__(name)
        self.eType = eType
        self.default_value = default_value
        if from_string:
            self.from_string = from_string

    def from_string(self, value):
        return value

    def __repr__(self):
        etype = self.eType.__name__ if self.eType else None
        return '{0}({1})'.format(self.name, etype)


class EEnum(EDataType):
    def __init__(self, name=None, default_value=None, literals=None):
        super().__init__(name, eType=self)
        if literals:
            for i, lit_name in enumerate(literals):
                lit_name = '_' + lit_name if lit_name[:1].isnumeric() \
                                          else lit_name
                literal = EEnumLiteral(i, lit_name)
                self.eLiterals.append(literal)
                self.__setattr__(lit_name, literal)
        if default_value:
            self.default_value = self.__getattribute__(default_value)
        elif not default_value and literals:
            self.default_value = self.eLiterals[0]

    def __contains__(self, key):
        if isinstance(key, EEnumLiteral):
            return key in self.eLiterals
        return any(lit for lit in self.eLiterals if lit.name == key)

    def getEEnumLiteral(self, name=None, value=0):
        try:
            if name:
                return next(lit for lit in self.eLiterals if lit.name == name)
            return next(lit for lit in self.eLiterals if lit.value == value)
        except StopIteration:
            return None

    def __repr__(self):
        return self.name + str(self.eLiterals)


class EEnumLiteral(ENamedElement):
    def __init__(self, value=0, name=None):
        super().__init__(name)
        self.value = value

    def __repr__(self):
        return '{0}={1}'.format(self.name, self.value)


class EStructuralFeature(ETypedElement):
    def __init__(self, name=None, eType=None, ordered=True, unique=True,
                 lower=0, upper=1, required=False, changeable=True,
                 volatile=False, transient=False, unsettable=False,
                 derived=False):
        super().__init__(name, eType, ordered, unique, lower, upper, required)
        self.changeable = changeable
        self.volatile = volatile
        self.transient = transient
        self.unsettable = unsettable
        self.derived = derived

    def __repr__(self):
        return '{0}: {1}'.format(self.name, self.eType)


class EAttribute(EStructuralFeature):
    def __init__(self, name=None, eType=None, default_value=None,
                 lower=0, upper=1, changeable=True, derived=False):
        super().__init__(name, eType, lower=lower, upper=upper,
                         derived=derived, changeable=changeable)
        self.default_value = default_value
        if not self.default_value and isinstance(eType, EDataType):
            self.default_value = eType.default_value


class EReference(EStructuralFeature):
    def __init__(self, name=None, eType=None, lower=0, upper=1,
                 containment=False, eOpposite=None, ordered=True, unique=True,
                 derived=False):
        super().__init__(name, eType, ordered, unique, lower=lower,
                         upper=upper, derived=derived)
        self.containment = containment
        self.eOpposite = eOpposite
        if eOpposite:
            eOpposite.eOpposite = self
        if not isinstance(eType, EClass) and hasattr(eType, 'eClass'):
            self.eType = eType.eClass


class EClass(EClassifier):
    def __init__(self, name=None, superclass=None, abstract=False):
        super().__init__(name)
        self.abstract = abstract
        if isinstance(superclass, tuple):
            [self.eSuperTypes.append(x) for x in superclass]
        elif isinstance(superclass, EClass):
            self.eSuperTypes.append(superclass)
        self.__metainstance = type(self.name, (EObject,), {
                                    'eClass': self,
                                    '__getattribute__': Core.getattr,
                                    '__setattr__': Core.setattr
                                })

    def __call__(self, *args, **kwargs):
        if self.abstract:
            raise TypeError("Can't instantiate abstract EClass {0}"
                            .format(self.name))
        obj = self.__metainstance()
        obj._isready = True
        return obj

    def __repr__(self):
        return '<EClass name="{0}">'.format(self.name)

    @property
    def eAttributes(self):
        return list(filter(lambda x: isinstance(x, EAttribute),
                           self.eStructuralFeatures))

    @property
    def eReferences(self):
        return list(filter(lambda x: isinstance(x, EReference),
                           self.eStructuralFeatures))

    def findEStructuralFeature(self, name):
        return next(
                (f for f in self.eAllStructuralFeatures() if f.name == name),
                None)

    def eAllSuperTypes(self, building=None):
        if isinstance(self, type):
            return {x.eClass for x in self.mro() if x is not object and
                    x is not self}
        if not self.eSuperTypes:
            return set()
        building = building if building else []
        stypes = set()
        [stypes.add(x) for x in self.eSuperTypes if x not in building]
        for ec in self.eSuperTypes:
            stypes |= (ec.eAllSuperTypes(stypes))
        return stypes

    def eAllStructuralFeatures(self):
        feats = list(self.eStructuralFeatures)
        [feats.extend(x.eStructuralFeatures) for x in self.eAllSuperTypes()]
        return feats

    def eAllOperations(self):
        ops = list(self.eOperations)
        [ops.extend(x.eOperations) for x in self.eAllSuperTypes()]
        return ops

    def findEOperation(self, name):
        return next((f for f in self.eAllOperations() if f.name == name), None)


EClass.eClass = EClass


# Meta methods for static EClass
class MetaEClass(type):
    def __init__(cls, name, bases, nmspc):
        super().__init__(name, bases, nmspc)
        cls.__getattribute__ = Core.getattr
        cls.__setattr__ = Core.setattr
        Core._promote(cls)

    def __call__(cls, *args, **kwargs):
        if cls.eClass.abstract:
            raise TypeError("Can't instantiate abstract EClass {0}"
                            .format(cls.eClass.name))
        obj = type.__call__(cls, *args, **kwargs)
        # init instances by reflection
        EObject.__subinit__(obj)
        for efeat in reversed(obj.eClass.eAllStructuralFeatures()):
            if efeat.name in obj.__dict__:
                continue
            if isinstance(efeat, EAttribute):
                obj.__setattr__(efeat.name, efeat.default_value)
            elif efeat.many:
                obj.__setattr__(efeat.name, ECollection.create(obj, efeat))
            else:
                obj.__setattr__(efeat.name, None)
        obj._isready = True
        return obj


def abstract(cls):
    cls.eClass.abstract = True
    return cls


# meta-meta level
EString = EDataType('EString', str)
EBoolean = EDataType('EBoolean', bool, False,
                     from_string=lambda x: x in ['True', 'true'])
EInteger = EDataType('EInteger', int, 0, from_string=lambda x: int(x))
EStringToStringMapEntry = EDataType('EStringToStringMapEntry', dict, {})
EDiagnosticChain = EDataType('EDiagnosticChain', str)

EModelElement.eAnnotations = EReference('eAnnotations', EAnnotation,
                                        upper=-1, containment=True)
EAnnotation.eModelElement = EReference('eModelElement', EModelElement,
                                       eOpposite=EModelElement.eAnnotations)
EAnnotation.source = EAttribute('source', EString)
EAnnotation.details = EAttribute('details', EStringToStringMapEntry)
EAnnotation.references = EReference('references', EObject, upper=-1)
EAnnotation.contents = EReference('contents', EObject, upper=-1)

ENamedElement.name = EAttribute('name', EString)

ETypedElement.ordered = EAttribute('ordered', EBoolean, default_value=True)
ETypedElement.unique = EAttribute('unique', EBoolean, default_value=True)
ETypedElement.lower = EAttribute('lower', EInteger, derived=True)
ETypedElement.lowerBound = EAttribute('lowerBound', EInteger)
ETypedElement.upper = EAttribute('upper', EInteger,
                                 default_value=1, derived=True)
ETypedElement.upperBound = EAttribute('upperBound', EInteger, default_value=1)
ETypedElement.required = EAttribute('required', EBoolean)
ETypedElement.eType = EReference('eType', EClassifier)
ETypedElement.default_value = EAttribute('default_value', type)

EStructuralFeature.changeable = EAttribute('changeable', EBoolean,
                                           default_value=True)
EStructuralFeature.volatile = EAttribute('volatile', EBoolean)
EStructuralFeature.transient = EAttribute('transient', EBoolean)
EStructuralFeature.unsettable = EAttribute('unsettable', EBoolean)
EStructuralFeature.derived = EAttribute('derived', EBoolean)
EStructuralFeature.defaultValueLiteral = EAttribute('defaultValueLiteral',
                                                    EString)


EPackage.nsURI = EAttribute('nsURI', EString)
EPackage.nsPrefix = EAttribute('nsPrefix', EString)
EPackage.eClassifiers = EReference('eClassifiers', EClassifier,
                                   upper=-1, containment=True)
EPackage.eSubpackages = EReference('eSubpackages', EPackage,
                                   upper=-1, containment=True)
EPackage.eSuperPackage = EReference('eSuperPackage', EPackage,
                                    lower=1, eOpposite=EPackage.eSubpackages)

EClassifier.ePackage = EReference('ePackage', EPackage,
                                  eOpposite=EPackage.eClassifiers)
EClassifier.eTypeParameters = EReference('eTypeParameters', ETypeParameter,
                                         upper=-1, containment=True)

EDataType.instanceClassName = EAttribute('instanceClassName', EString)
EDataType.serializable = EAttribute('serializable', EBoolean)

EClass.abstract = EAttribute('abstract', EBoolean)
EClass.eStructuralFeatures = EReference('eStructuralFeatures',
                                        EStructuralFeature,
                                        upper=-1, containment=True)
EClass._eAttributes = EReference('eAttributes', EAttribute,
                                 upper=-1, derived=True)
EClass._eReferences = EReference('eReferences', EReference,
                                 upper=-1, derived=True)
EClass.eSuperTypes = EReference('eSuperTypes', EClass, upper=-1)
EClass.eOperations = EReference('eOperations', EOperation,
                                upper=-1, containment=True)
EClass.instanceClassName = EAttribute('instanceClassName', EString)

EStructuralFeature.eContainingClass = \
                   EReference('eContainingClass', EClass,
                              eOpposite=EClass.eStructuralFeatures)

EReference.containment = EAttribute('containment', EBoolean)
EReference.eOpposite = EReference('eOpposite', EReference)
EReference.resolveProxies = EAttribute('resolveProxies', EBoolean)

EEnum.eLiterals = EReference('eLiterals', EEnumLiteral, upper=-1,
                             containment=True)

EEnumLiteral.eEnum = EReference('eEnum', EEnum, eOpposite=EEnum.eLiterals)
EEnumLiteral.name = EAttribute('name', EString)
EEnumLiteral.value = EAttribute('value', EString)

EOperation.eParameters = EReference('eParameters', EParameter, upper=-1)
EOperation.eExceptions = EReference('eExceptions', EClassifier, upper=-1)
EOperation.eTypeParameters = EReference('eTypeParameters', ETypeParameter,
                                        upper=-1, containment=True)

EParameter.eOperation = EReference('eOperation', EOperation)

ETypeParameter.eBounds = EReference('eBounds', EGenericType,
                                    upper=-1, containment=True)
ETypeParameter.eGenericType = EReference('eGenericType', EGenericType,
                                         upper=-1)

Core._promote(EModelElement)
Core._promote(ENamedElement)
Core._promote(EGenericType)
Core._promote(ETypeParameter)
Core._promote(EAnnotation)
Core._promote(EPackage)
Core._promote(ETypedElement)
Core._promote(EClassifier)
Core._promote(EDataType)
Core._promote(EEnum)
Core._promote(EEnumLiteral)
Core._promote(EParameter)
Core._promote(EOperation)
Core._promote(EClass)
Core._promote(EStructuralFeature)
Core._promote(EAttribute)
Core._promote(EReference)

# We compute all the Metaclasses from the current module (EPackage-alike)
eClassifiers = Core.compute_eclass(__name__)
__btypes = [EString,
            EBoolean,
            EInteger,
            EStringToStringMapEntry,
            EDiagnosticChain]
__basic_types = {v.name: v for v in __btypes}
eClassifiers.update(__basic_types)
eClass = EPackage.eClass