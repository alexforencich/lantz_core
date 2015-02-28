# -*- coding: utf-8 -*-
"""
    lantz.has_features
    ~~~~~~~~~~~~~~~~~~

    HasFeatures is the most basic object in Lantz.

    It handles the use of Features, Subsystem, and Channel and the possibility
    to customize Feature behaviour by defining specially named methods..

    :copyright: 2015 by Lantz Authors, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.

"""
from __future__ import (division, unicode_literals, print_function,
                        absolute_import)
from future.utils import with_metaclass
from types import FunctionType, MethodType
from functools import update_wrapper
from inspect import cleandoc, getsourcelines
from itertools import chain
from textwrap import fill
from abc import ABCMeta
from collections import defaultdict

from .features.feature import Feature

# Prefixes for Features and Action specially named methods.
PRE_GET_PREFIX = '_pre_get_'
GET_PREFIX = '_get_'
POST_GET_PREFIX = '_post_get_'
PRE_SET_PREFIX = '_pre_set_'
SET_PREFIX = '_set_'
POST_SET_PREFIX = '_post_set_'

CUSTOMIZABLE = ((PRE_GET_PREFIX, 'pre_get'), (GET_PREFIX, 'get'),
                (POST_GET_PREFIX, 'post_get'),
                (PRE_SET_PREFIX, 'pre_set'), (SET_PREFIX, 'set'),
                (POST_SET_PREFIX, 'post_set'))


def wrap_custom_feat_methods(cls, meth_name, feat):
    """ Wrap a HasFeature method to make it an instance method of a Feature.

    This is necessary so that users can define overriding method in a natural
    way in the HasFeatures subclass assuming that the instance object will be
    passed as first argument and the Feature object as second when in reality
    it will be the other way round due to python binding mechanism.

    Parameters
    ----------
    cls : type
        Class on which the method which should override the default behaviour
        of the Feature is defined.
    meth_name : unicode
        Name of the method which should be used to override the default
        behaviour of the Feature.
    feat : Feature
        Instance of Feature whose default behaviour should be overridden.

    Returns
    -------
    wrapped : MethodType
        Method object which can be

    """
    wrapped = getattr(cls, meth_name).__func__

    def wrapper(iprop, instance, *args, **kwargs):
        return wrapped(instance, iprop, *args, **kwargs)

    update_wrapper(wrapper, wrapped)
    wrapper.__wrapped__ = wrapped
    return MethodType(wrapper, feat)


class set_feat(object):
    """Placeholder use to alter a feature in a subclass.

    This can be used to lightly alter a Feature defined on a parent class
    by for example changing the retries or the getter but without
    rewriting everything.

    Parameters
    ----------
    **kwargs
        New keyword arguments to pass to the constructor to alter the Feature.

    """
    def __init__(self, **kwargs):
        self.custom_attrs = kwargs

    def customize(self, feat):
        """Customize a feature using the given kwargs.

        """
        cls = type(feat)
        kwargs = feat.creation_kwargs.copy()
        kwargs.update(self.custom_attrs)
        new = cls(**kwargs)
        new.name = feat.name
        # Now set the method modifiers if any.
        ndict = new.__dict__
        for k, v in feat.__dict__.items():
            if k not in ndict:
                if isinstance(v, MethodType):
                    setattr(new, k, MethodType(v.__func__, new))
                else:
                    setattr(new, k, v)
        return new


# Sentinel returned when decorating a method with a subpart.
SUBPART_FUNC = object()


class _subpart(object):
    """Sentinel used to collect declarations or modifications for a subpart.

    Parameters
    ----------
    bases : class or tuple of classes, optional
        Class or classes to use as base class when no matching subpart exists
        on the driver.

    """
    def __init__(self, bases=()):
        self._name_ = ''
        if not isinstance(bases, tuple):
            bases = (bases,)
        self._bases_ = bases
        self._parent_ = None
        self._aliases_ = []

    def __setattr__(self, name, value):
        if isinstance(value, _subpart):
            value._parent_ = self
        object.__setattr__(self, name, value)

    def __call__(self, func):
        """Decorator maker to register functions in the subpart.

        The function is stored in the object under its own name.

        Returns
        -------
        ret : SUBPART_FUNC
            Dummy letting the metaclass to remove this from the class
            definition.

        """
        object.__setattr__(self, func.__name__, func)
        return SUBPART_FUNC

    def __enter__(self):
        """Using this a context manager helps readability and can allow to
        use shorter names in declarations.

        """
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """"Using this a context manager helps readability and can allow to
        use shorter names in declarations.

        """
        pass


class subsystem(_subpart):
    """Sentinel used to collect declarations or modifications for a subsystem.

    Parameters
    ----------
    bases : class or tuple of classes, optional
        Class or classes to use as base class when no matching subpart exists
        on the driver.

    """
    pass


class channel(_subpart):
    """Sentinel used to collect declarations or modifications for a channel.


    Parameters
    ----------
    list_available_method_name : unicode
        Name of the parent method to call to know which channels exist.

    bases : class or tuple of classes, optional
        Class or classes to use as base class when no matching subpart exists
        on the driver.

    """
    def __init__(self, list_available_method_name, bases=()):
        super(channel, self).__init__(bases)
        self._list_available_ = list_available_method_name


def make_cls_from_subpart(parent_name, part_name, part, base, docs):
    """Dynamically creates a subclass from a subpart object.

    Parameters
    ----------
    parent_name : unicode
        Name of the parent class system. Used to build the name of the new
        class.

    part_name : unicode
        Name of the attribute on the parent in which the new class will be
        stored. The name of the class will be the constraction of the parent
        name and of this name.

    part : _subpart
        _subpart object containing the class definition.

    base : type
        Base type for the new class. Will be prepended to any class specified
        in the subpart declaration.

    docs : dict
        Dictionary containing the docstring collected on the parent.

    """
    # If provided prepend base to declared base classes.
    if base:
        bases = tuple([base] + list(part._bases_))

    # Otherwise check that we have a SubSystem or Channel subclass in the
    # mro and if not prepend it.
    else:
        bases = part._bases_
        if (isinstance(part, subsystem) and
                (not bases or not issubclass(bases[0], AbstractSubSystem))):
            from .subsystem import SubSystem
            bases = tuple([SubSystem] + list(bases))
        elif (isinstance(part, channel) and
                (not bases or not issubclass(bases[0], AbstractChannel))):
            from .channel import Channel
            bases = tuple([Channel] + list(bases))

    # Extract the docstring specific to this subpart.
    print(docs)
    part_doc = docs.get(part_name, '')
    s_docs = {tuple(k.split('.', 1)): v for k, v in docs.items()}
    docs = {k[-1]: v for k, v in s_docs.items()
            if k[0] in part._aliases_ and len(k) == 2}

    meta = type(bases[0])
    # Python 2 fix : class name can't be unicode
    name = str(parent_name + part_name.capitalize())
    dct = dict(part.__dict__)
    del dct['_name_']
    del dct['_parent_']
    del dct['_bases_']
    del dct['_aliases_']
    dct['_docs_'] = docs
    new_class = meta(name, bases, dct)
    new_class.__doc__ = part_doc
    return new_class


class AbstractHasFeatures(with_metaclass(ABCMeta, object)):
    """Sentinel class for the collections of Features.

    """
    pass


class AbstractSubSystem(with_metaclass(ABCMeta, object)):
    """Sentinel for subsystem identification.

    """
    pass

AbstractHasFeatures.register(AbstractSubSystem)


class AbstractChannel(with_metaclass(ABCMeta, object)):
    """Sentinel class for channel identification.

    """
    pass

AbstractHasFeatures.register(AbstractChannel)


class HasFeaturesMeta(type):
    """ Metaclass handling Feature customisation, subsystems registration...

    """
    def __new__(meta, name, bases, dct):
        # Pass over the class dict once and collect the information
        # necessary to implement the various behaviours.
        feats = {}                       # Feature declarations
        subsystems = {}                  # Subsystem declarations
        channels = {}                    # Channels declaration
        subparts = {}                    # Declared subparts
        cust_feats = {'pre_get': [],     # Pre get methods _pre_get_*
                      'get': [],         # Get methods: _get_*
                      'post_get': [],    # Post get methods: _post_get_*
                      'pre_set': [],     # Pre set methods: _pre_set_*
                      'set': [],         # Set methods: _set_*
                      'post_set': []     # Post set methods: _post_set_*
                      }
        feat_paras = {}                  # Sentinels changing feats behavior.

        # List of the entries to remove from the class because they are
        # destinated to a subpart.
        to_remove = []

        docs = dct.pop('_docs_') if '_docs_' in dct else None
        print(docs)

        # Set of seen subparts to avoid counting multiple times the same one
        # which ahappens due to the context manager use.
        seen_subparts = set()

        # First we identify all elements in the passed dict to clean it up
        # before creating the class.
        for key, value in dct.iteritems():
            if value is SUBPART_FUNC:
                to_remove.append(key)

            elif isinstance(value, _subpart):
                if key in subparts:
                    msg = 'Attempt to redeclare subpart {}'
                    raise KeyError(msg.format(key))
                if value not in seen_subparts:
                    value._name_ = key
                    subparts[key] = value
                    seen_subparts.add(value)
                elif len(key) > len(value._name_):
                    subparts[key] = value
                    del subparts[value._name_]
                    to_remove.append(value._name_)
                    value._name_ = key
                else:
                    to_remove.append(key)
                value._aliases_.append(key)

            elif isinstance(value, Feature):
                feats[key] = value
                value.name = key

            elif isinstance(value, set_feat):
                feat_paras[key] = value

            elif isinstance(value, FunctionType):
                if key.startswith(POST_GET_PREFIX):
                    cust_feats['post_get'].append(key)
                elif key.startswith(PRE_SET_PREFIX):
                    cust_feats['pre_set'].append(key)
                elif key.startswith(POST_SET_PREFIX):
                    cust_feats['post_set'].append(key)
                elif key.startswith(PRE_GET_PREFIX):
                    cust_feats['pre_get'].append(key)
                elif key.startswith(GET_PREFIX):
                    cust_feats['get'].append(key)
                elif key.startswith(SET_PREFIX):
                    cust_feats['set'].append(key)

        # Clean up class dictionary.
        for k in chain(feat_paras, to_remove, subparts):
            del dct[k]

        # Create the class object.
        cls = super(HasFeaturesMeta, meta).__new__(meta, name, bases, dct)

        # Purge the list of base classes (for the most base class object is
        # present)
        bases = [b for b in bases if issubclass(b, AbstractHasFeatures)]

        # Analyse the source code to find the doc for the defined Features.
        # This will work as long as two subpart are not aliased in the same
        # way which is probabbly good enough.
        if docs is None:
            docs = {}
            lines, _ = getsourcelines(cls)
            doc = ''
            for line in lines:
                l = line.strip()
                if l.startswith('#:'):
                    doc += ' ' + l[2:].strip()
                elif ' = ' in l:
                    attr_name = l.split(' = ', 1)[0]
                    docs[attr_name] = doc.strip()
                    doc = ''

        # Make the feature build their docs from the provided docstrings.
        for f in feats:
            if f in docs:
                feats[f].make_doc(docs[f])

        # Handle the subparts by creating dynamic subclasses.
        inherited_ss = dict([(k, v) for b in bases
                             for k, v in b.__subsystems__.items()])
        inherited_ch = dict([(k, v) for b in bases
                             for k, v in b.__channels__.items()])
        for k in subparts:
            part = subparts[k]
            part_name = k
            if not hasattr(part, 'retries_exceptions'):
                part.retries_exceptions = cls.retries_exceptions
            # If a subpart with the same name has already been declared on a
            # parent class we use its class as a base class for the one we are
            # about to create.
            if k in inherited_ss:
                subsystems[part_name] = make_cls_from_subpart(name, part_name,
                                                              part,
                                                              inherited_ss[k],
                                                              docs)
            elif k in inherited_ch:
                ch_cls = make_cls_from_subpart(name, part_name,
                                               part, inherited_ch[k],
                                               docs)
                channels[part_name] = (ch_cls, part._list_available_)

            else:
                if isinstance(part, subsystem):
                    subsystems[part_name] = make_cls_from_subpart(name,
                                                                  part_name,
                                                                  part, None,
                                                                  docs)
                elif isinstance(part, channel):
                    ch_cls = make_cls_from_subpart(name, part_name, part,
                                                   None, docs)
                    channels[part_name] = (ch_cls, part._list_available_)

        # Put references to the subsystem and channel classes on the class.
        for k, v in subsystems.items():
            setattr(cls, k, v)
        for k, v in channels.items():
            setattr(cls, k, v[0])

        inherited_ss.update(subsystems)
        subsystems = inherited_ss
        inherited_ch.update(channels)
        channels = inherited_ch

        # Walk the mro of the class, excluding itself, in reverse order
        # collecting all of the feats into a single dict. The reverse
        # update preserves the mro of overridden features.
        base_feats = {}
        for base in reversed(cls.__mro__[1:-1]):
            if base is not AbstractHasFeatures \
                    and issubclass(base, AbstractHasFeatures):
                base_feats.update(base.__feats__)

        # The set of iprops which live on this class as opposed to a
        # base class. This enables the code which hooks up the various
        # static behaviours to only clone a iprops when necessary.
        owned_feats = set(feats.keys())

        all_feats = dict(base_feats)
        all_feats.update(feats)

        # Clone and customize feature for which a set_feat has been
        # declared.
        for k, v in feat_paras.items():
            feat = v.customize(all_feats[k])
            owned_feats.add(k)
            all_feats[k] = feat
            setattr(cls, k, feat)

        # Add the special statically defined behaviours for the features.
        # If the target feature is defined on a parent class, it is cloned
        # so that the behaviour of the parent class is not modified.

        def clone_if_needed(feat):
            if feat.name not in owned_feats:
                feat = feat.clone()
                all_feats[feat.name] = feat
                feats[feat.name] = feat
                owned_feats.add(feat)
                setattr(cls, feat.name, feat)
            return feat

        def customize_feats(cls, feats, prefix, feat_meth):
            n = len(prefix)
            for mangled in feats:
                target = mangled[n:]
                if target in all_feats:
                    feat = clone_if_needed(all_feats[target])
                    wrapped = wrap_custom_feat_methods(cls, mangled, feat)
                    setattr(feat, feat_meth, wrapped)
                else:
                    mess = cleandoc('''{} has no Feature {} whose behaviour
                                    can be customised''')
                    raise AttributeError(mess.format(cls, target))

        for prefix, attr in CUSTOMIZABLE:
            customize_feats(cls, cust_feats[attr], prefix, attr)

        # Put a reference to the features dict on the class. This is used
        # by HasFeaturesMeta to query for the features.
        cls.__feats__ = feats

        # Put a reference to the subsystems in the class.
        # This is used at initialisation to create the appropriate subsystems
        cls.__subsystems__ = subsystems

        # Put a reference to the channels in the class
        cls.__channels__ = channels

        return cls


class HasFeatures(with_metaclass(HasFeaturesMeta, object)):
    """ Base class for objects using the IProperties mechanisms.

    """
    #: Tuple of iproperties names which shoulb be cached by default.
    caching_permissions = ()

    #: Tuple of exception to consider when securing a communication (either via
    #: secure_communication decorator or for iproperties with a non zero
    #: retries value)
    retries_exceptions = ()

    def __init__(self, caching_allowed=True):

        self._cache = {}
        self._limits_cache = {}
        self._proxies = {}

        subsystems = self.__subsystems__
        channels = self.__channels__

        self.use_cache = caching_allowed

        # Initializing subsystems.
        for ss, cls in subsystems.items():
            subsystem = cls(self, caching_allowed=caching_allowed)
            setattr(self, ss, subsystem)

        # Creating a channel container for each kind of declared channels.
        for ch, (cls, listing) in channels.items():
            from .channel import ChannelContainer
            ch_holder = ChannelContainer(cls, self, ch, listing)
            setattr(self, ch, ch_holder)

    def get_feat(self, name):
        """ Acces the feature matching the given name.

        Parameters
        ----------
        name : unicode
            Name of the Feature to be retrieved

        Returns
        -------
        iprop : Feature
            Matching Feature object

        """
        return getattr(self.__class__, name)

    def clear_cache(self, subsystems=True, channels=True, features=None):
        """ Clear the cache of all the features or only of the specified
        ones.

        Parameters
        ----------
        subsystems : bool, optional
            Whether or not to clear the subsystems. This argument is used only
            if properties is None.
        channels : bool, optional
            Whether or not to clear the channels. This argument is used only
            if properties is None.
        features : iterable of str, optional
            Name of the properties whose cache should be cleared. Dotted names
            can be used to access subsystems and channels. When accessing
            channels the cache of all instances is cleared. All caches
            will be cleared if not specified.

        """
        cache = self._cache
        if features:
            sss = defaultdict(list)
            chs = defaultdict(list)
            for name in features:
                if '.' in name:
                    aux, n = name.split('.', 1)
                    if aux in self.__subsystems__:
                        sss[aux].append(n)
                    else:
                        chs[aux].append(n)
                elif name in cache:
                    del cache[name]

            for ss in sss:
                getattr(self, ss).clear_cache(properties=sss[ss])

            if self.__channels__:
                for ch in chs:
                    for o in self._channel_cache.get(ch, {}).values():
                        o.clear_cache(properties=chs[ch])
        else:
            self._cache = {}
            if subsystems:
                for ss in self.__subsystems__:
                    getattr(self, ss).clear_cache(channels=channels)
            if channels and self.__channels__:
                for chs in self._channel_cache.values():
                    for ch in chs.values():
                        ch.clear_cache(subsystems)

    def check_cache(self, subsystems=True, channels=True, properties=None):
        """Return the value of the cache of the object.

        The cache values for the subsystems and channels are not accessible.

        Parameters
        ----------
        subsystems : bool, optional
            Whether or not to include the subsystems caches. This argument is
            used only if properties is None.
        channels : bool, optional
            Whether or not to include the channels caches. This argument is
            used only if properties is None.
        properties : iterable of str, optional
            Name of the properties whose cache should be cleared. All caches
            will be cleared if not specified.

        Returns
        -------
        cache : dict
            Dict containing the cached value, if the properties arg is given
            None will be returned for the field with no cached value.

        """
        cache = {}
        if properties:
            sss = defaultdict(list)
            chs = defaultdict(list)
            for name in properties:
                if '.' in name:
                    aux, n = name.split('.', 1)
                    if aux in self.__subsystems__:
                        sss[aux].append(n)
                    else:
                        chs[aux].append(n)
                elif name in self._cache:
                    cache[name] = self._cache[name]

            for ss in sss:
                cache[ss] = getattr(self, ss).check_cache(properties=sss[ss])

            if self.__channels__:
                for ch in chs:
                    ch_cache = {}
                    cache[ch] = ch_cache
                    for ch_id, o in self._channel_cache.get(ch, {}).items():
                        ch_cache[ch_id] = o.check_cache(properties=chs[ch])
        else:
            cache = self._cache.copy()
            if subsystems:
                for ss in self.__subsystems__:
                    cache[ss] = getattr(self, ss)._cache.copy()

            if channels:
                for chs, ch_dict in self._channel_cache.items():
                    ch_cache = {}
                    cache[chs] = ch_cache
                    for ch in ch_dict:
                        ch_cache[ch] = ch_dict[ch]._cache.copy()

        return cache

    def reopen_connection(self):
        """Reopen the connection to the instrument.

        """
        message = fill(cleandoc(
            '''This method is used to reopen a connection whose state
            is suspect, for example the last message sent did not
            go through, and should be implemented by classes
            subclassing HasIProps'''),
            80)
        raise NotImplementedError(message)

    def default_get_feature(self, feat, cmd, *args, **kwargs):
        """Method used by default by the IProperty to retrieve a value from an
        instrument.

        Parameters
        ----------
        feat : Feature
            Reference to the property issuing this call.
        cmd :
            Command used by the implementation to determine what should be done
            to get the answer from the instrument.
        *args :
            Additional arguments necessary to retrieve the instrument state.
        **kwargs :
            Additional keywords arguments necessary to retrieve the instrument
            state.

        """
        mess = fill(cleandoc('''Method used by default by the Feature to
            retrieve a value from an instrument. Should be implemented by
            classes subclassing HasFeatures.'''), 80)
        raise NotImplementedError(mess)

    def default_set_feature(self, feat, cmd, *args, **kwargs):
        """Method used by default by the IProperty to set an instrument value.

        Parameters
        ----------
        feat : Feature
            Reference to the property issuing this call.
        cmd :
            Command used by the implementation to determine what should be done
            to set the instrument state.
        *args :
            Additional arguments necessary to retrieve the instrument state.
        **kwargs :
            Additional keywords arguments necessary to retrieve the instrument
            state.

        """
        mess = fill(cleandoc('''Method used by default by the Feature to
            set an instrument value. Should be implemented by
            classes subclassing HasFeatures'''), 80)
        raise NotImplementedError(mess)

    def default_check_operation(self, feat, value, i_value, state=None):
        """Method used by default by the IProperty to check the instrument
        operation.

        Parameters
        ----------
        feat : Feature
            Reference to the Feature issuing this call.
        value :
            Value assigned by the user.
        i_value :
            Value computed by the pre_set method of the Feature.
        state : optional
            State of the instrument if already known.

        Returns
        -------
        result : bool
            Is everything ok ? Can we assume that the last operation succeeded.
        precision :
            Any precision about the situation, this can be any object but
            something should always be returned.

        """
        mess = fill(cleandoc('''Method used by default by the Feature to
            check the instrument operation. Should be implemented by
            classes subclassing HasFeatures.'''), 80)
        raise NotImplementedError(mess)


AbstractHasFeatures.register(HasFeatures)