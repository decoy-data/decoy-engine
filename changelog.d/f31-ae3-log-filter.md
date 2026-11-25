### Security (log records carry no exception text, F31 AE3, 2026-11-24)

Every log handler the engine builds now carries `decoy_engine.safe_output.SafeRecordFilter`. An exception passed as a log argument prints as its type name, and a logged traceback prints only the exception type and the file, line and function of each frame. A traceback text cached by another handler is not printed. A host program can attach the same filter to its own handlers. The disguise loader, Faker locale fallback, memory monitor and model pack loader no longer log exception messages.

Host log handlers that run after the engine handler (for example Sentry integrations) no longer see the exception object, because the filter clears `exc_info` on the record.

A mapping argument that is not a plain `dict` (a `Counter`, `OrderedDict`, `defaultdict`, `UserDict`, `mappingproxy`, `ChainMap` or a caller `Mapping`) prints as `<mapping>` in engine logs, and so does a `dict` with a key that is not a `str`, `int`, `float`, `bool` or `None`. Pass `dict(counter)` at the call site to print its items.

A list, tuple, set, frozenset or dict that sits deeper than the filter scans prints as `<nested>`, and a `str` subclass prints as a plain `str`, so an exception inside a deeply nested argument cannot print its text.

Any other iterable (a generator, a custom class with `__iter__`, an array library object) prints as `<nested>`, a dataclass or attrs instance prints as `<object>`, and a `deque`, dict view or `slice` is shown with its exception items as labels. Attributes passed with `extra=` go through the same filter.
