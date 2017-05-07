""" This module introduce the command system which allows to defined various
that can be executed onto a commands stack. Each command can also be 'undo' and
'redo'.
"""
from abc import ABC, abstractmethod
from collections import MutableSequence
from pyecore.ecore import EObject
import ordered_set


# monkey patching the OrderedSet implementation
def insert(self, index, key):
    """Adds an element at a dedicated position in an OrderedSet.

    This implementation is meant for the OrderedSet from the ordered_set
    package only.
    """
    if key in self.map:
        return
    self.items.insert(index, key)
    self.map[key] = index
    for k, v in self.map.items():
        if v >= index:
            self.map[k] = v + 1


def pop(self, index=None):
    """Removes an element at the tail of the OrderedSet or at a dedicated
    position.

    This implementation is meant for the OrderedSet from the ordered_set
    package only.
    """
    if not self.items:
        raise KeyError('Set is empty')

    def remove_index(i):
        elem = self.items[i]
        del self.items[i]
        del self.map[elem]
        return elem
    if index is None:
        elem = remove_index(-1)
    else:
        elem = remove_index(index)
        for k, v in self.map.items():
            if v >= index:
                self.map[k] = v - 1
    return elem


ordered_set.OrderedSet.insert = insert
ordered_set.OrderedSet.pop = pop


class Command(ABC):
    """Provides the basic elements that must be implemented by a custom command.
    The methods/properties that need to be implemented are:
    * can_execute (@property)
    * can_undo (@property)
    * execute (method)
    * undo (method)
    * redo (method)
    """
    @property
    @abstractmethod
    def can_execute(self):
        pass

    @abstractmethod
    def execute(self):
        pass

    @property
    @abstractmethod
    def can_undo(self):
        pass

    @abstractmethod
    def undo(self):
        pass


class AbstractCommand(Command):
    def __init__(self, owner=None, feature=None, value=None, label=None):
        if owner and not isinstance(owner, EObject):
            raise BadValueError(got=owner, expected=EObject)
        self.owner = owner
        self.feature = feature
        self.value = value
        self.previous_value = None
        self.label = label
        self._is_prepared = False
        self._is_executable = False

    @property
    def can_execute(self):
        execute = False
        eclass = self.owner.eClass
        if isinstance(self.feature, str):
            actual = eclass.findEStructuralFeature(self.feature)
            self.feature = actual
            execute = actual is not None
        else:
            actual = eclass.findEStructuralFeature(self.feature.name)
            execute = self.feature is actual
        return execute

    @property
    def can_undo(self):
        return self._executed

    def execute(self):
        self.do_execute()
        self._executed = True

    def __repr__(self):
        if not isinstance(self.feature, str):
            feature = self.feature.name
        else:
            feature = self.feature
        return '{} {}.{} <- {}'.format(self.__class__.__name__,
                                       self.owner,
                                       feature,
                                       self.value)


class Set(AbstractCommand):
    def __init__(self, owner=None, feature=None, value=None):
        super().__init__(owner, feature, value)

    @property
    def can_execute(self):
        can = super().can_execute
        return can and not self.feature.many

    def undo(self):
        self.owner.eSet(self.feature, self.previous_value)

    def redo(self):
        self.owner.eSet(self.feature, self.value)

    def do_execute(self):
        object = self.owner
        self.previous_value = self.owner.eGet(self.feature)
        self.owner.eSet(self.feature, self.value)


class Add(AbstractCommand):
    def __init__(self, owner=None, feature=None, value=None, index=None):
        super().__init__(owner, feature, value)
        self.index = index
        self._collection = None

    @property
    def can_execute(self):
        executable = super().can_execute
        executable = executable and self.value is not None
        self._collection = self.owner.eGet(self.feature)
        if self.index is not None:
            executable = executable and i >= 0 and i <= len(self._collection)
        return executable

    @property
    def can_undo(self):
        can = super().can_undo
        return can and self.value in self._collection

    def undo(self):
        self._collection.pop(self.index)

    def redo(self):
        self._collection.insert(self.index, self.value)

    def do_execute(self):
        object = self.owner
        if self.index is not None:
            self._collection.insert(self.index, self.value)
        else:
            self.index = len(self._collection)
            self._collection.append(self.value)


class Remove(AbstractCommand):
    def __init__(self, owner=None, feature=None, value=None, index=None):
        super().__init__(owner, feature, value)
        self.index = index
        self._collection = None

    @property
    def can_execute(self):
        executable = super().can_execute
        executable = executable and self.value is not None
        self._collection = self.owner.eGet(self.feature)
        if self.index is not None:
            executable = executable and i >= 0 and i <= len(self._collection)
        return executable

    @property
    def can_undo(self):
        can = super().can_undo
        return can

    def undo(self):
        self._collection.insert(self.index, self.value)

    def redo(self):
        self._collection.pop(self.index)

    def do_execute(self):
        if self.index is None:
            self.index = self._collection.index(self.value)
        self._collection.pop(self.index)


class Move(AbstractCommand):
    def __init__(self, owner=None, feature=None, from_index=None,
                 to_index=None, value=None):
        super().__init__(owner, feature, value=value)
        self.from_index = from_index
        self.to_index = to_index
        if bool(self.from_index is not None) == bool(self.value is not None):
            raise ValueError('Move command cannot have from_index and value '
                             'set together.')

    @property
    def can_execute(self):
        can = super().can_execute
        self._collection = self.owner.eGet(self.feature)
        in_bounds = self.to_index >= 0 and self.to_index >= 0
        if self.value is None:
            self.value = self._collection[self.from_index]
        if self.from_index is None:
            self.from_index = self._collection.index(self.value)
        in_bounds = in_bounds and self.from_index < len(self._collection)
        in_bounds = in_bounds and self.from_index >= 0
        return can and in_bounds and self.value in self._collection

    @property
    def can_undo(self):
        can = super().can_undo
        obj = self._collection[self.to_index]
        return obj is self.value

    def undo(self):
        object = self.owner
        self.value = self._collection.pop(self.to_index)
        self._collection.insert(self.from_index, self.value)

    def redo(self):
        self.do_execute()

    def do_execute(self):
        self.value = self._collection.pop(self.from_index)
        self._collection.insert(self.to_index, self.value)


class Compound(Command, MutableSequence):
    def __init__(self, *commands):
        super().__init__()
        self.items = commands

    @property
    def can_execute(self):
        return all(command.can_execute for command in self.items)

    def execute(self):
        for command in self:
            command.execute()

    @property
    def can_undo(self):
        return all(command.can_undo for command in self.items)

    def undo(self):
        for command in reversed(self):
            command.undo()

    def unwrap(self):
        return self[0] if len(self) == 1 else self

    def __delitem__(self, index):
        self.items.__delitem__(index)

    def __getitem__(self, index):
        return self.items.__getitem__(index)

    def __len__(self):
        return len(self.items)

    def __setitem__(self, index, item):
        return self.items.__setitem__(index, item)

    def insert(self, index, item):
        self.items.insert(index, item)

    def __iter__(self):
        return iter(self.items)

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, self.items)


class CommandStack(object):
    def __init__(self):
        self.stack = []
        self.stack_index = -1

    @property
    def top(self):
        return self.stack[self.stack_index]

    @property
    def peek_next_top(self):
        return self.stack[self.stack_index + 1]

    @top.setter
    def top(self, command):
        index = self.stack_index + 1
        self.stack[index:index] = [command]
        self.stack_index = index

    @top.deleter
    def top(self):
        self.stack_index -= 1

    def execute(self, *commands):
        for command in commands:
            if command.can_execute:
                command.execute()
                self.top = command
            else:
                raise ValueError('Cannot execute command {}'.format(command))

    def undo(self):
        if not self.stack:
            raise ValueError('Command stack is empty')
        if self.top.can_undo:
            self.top.undo()
            del self.top

    def redo(self):
        self.peek_next_top.redo()
