Breaking: a generate column `provider: lorem_text` now draws from a pool of Faker paragraphs, so its values change for a given seed. The column is still text.

### Added (computed Faker draws on more routes, GEN-NONFAKER-DRAWS S2, 2026-11-24)

- The sequential route runs `uuid` and `random_choice` over strings on its kernels, in deterministic and non-deterministic mode. The values equal the whole-frame run.
- The out-of-core route runs a deterministic `uuid` or string `random_choice` over a string source. Its output type comes from one descriptor, so `masked_output_type` reports `int64`, `float64` or `bool` for a numeric `random_int_range` or `random_choice`.
- A computed draw whose output is not `string` is declined before it runs, with the new reason `route/faker_computed_output_type_unsupported` on the chunked and sequential routes. A forced out-of-core run refuses it with `runtime/out_of_core_faker_computed_output_type_unsupported` before any write. Auto routing falls through to the whole frame.
- `lorem_text` is a pool provider. It joins the native faker allowlist, so it runs on the chunked, unified and out-of-core routes like the other string pool providers. `address_full` is still refused at compile.
- A computed draw follows the live provider binding. A provider rebound through `ProviderRegistry.override` takes the same variant (computed, pool, or unsupported) on the whole-frame, sequential and out-of-core routes. The out-of-core route declines a rebinding that differs from the stock one, including a pool rebound to an adapter that is not the stock string one.
- The out-of-core route runs a pool column under a registered Faker callback only when the live adapter cannot reach that callback for the column's locale. The adapter resolves a given, empty or omitted locale itself (`faker_callback_reachable`), so a Mimesis binding with another default locale and a Faker fallback is declined instead of failing in Arrow.
- An all-null or empty computed column is Arrow `string` on every route.
- A `uuid` draw is admitted only when its hash kernel is bound and passes its self-test. A column whose kernel is missing stays on pandas (sequential) or runs the byte-identical reference hash (out-of-core).
- Chunked and unified native execution of computed draws stays deferred to a follow-up slice.
- The chunked pool-type checks skip a computed draw, so a stock `uuid` or string `random_choice` never builds a pool there.
