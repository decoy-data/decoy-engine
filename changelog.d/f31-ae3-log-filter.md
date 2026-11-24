### Security (log records carry no exception text, F31 AE3, 2026-11-24)

Every log handler the engine builds now carries `decoy_engine.safe_output.SafeRecordFilter`. An exception passed as a log argument prints as its type name, and a logged traceback prints only the exception type and the file, line and function of each frame. A traceback text cached by another handler is not printed. A host program can attach the same filter to its own handlers. The disguise loader, Faker locale fallback, memory monitor and model pack loader no longer log exception messages.

Host log handlers that run after the engine handler (for example Sentry integrations) no longer see the exception object, because the filter clears `exc_info` on the record.
