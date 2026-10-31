# Changelog

## [4.0.5](https://github.com/rsionnach/nthlayer-generate/compare/v4.0.4...v4.0.5) (2026-10-31)


### Bug Fixes

* ship the Apache-2.0 LICENSE and declare it in package metadata (opensrm-bqfj) ([36e7dfc](https://github.com/rsionnach/nthlayer-generate/commit/36e7dfccf5d312f57ce6baacbd172434b1d947b5))
* ship the Apache-2.0 LICENSE and declare it in package metadata (opensrm-bqfj) ([b9e78ef](https://github.com/rsionnach/nthlayer-generate/commit/b9e78ef72d9ba6836ceabb01ab9f2a93e35f8dcd))

## [4.0.4](https://github.com/rsionnach/nthlayer-generate/compare/v4.0.3...v4.0.4) (2026-10-31)


### Bug Fixes

* apply --dry-run honours --output json (opensrm-wlt1) ([222aa0a](https://github.com/rsionnach/nthlayer-generate/commit/222aa0a751afd948158b411bec9690f0850652be))
* apply --dry-run honours --output json (opensrm-wlt1) ([b471afd](https://github.com/rsionnach/nthlayer-generate/commit/b471afd56c7ce80b9fc28b37e3a2c702072e05a3))

## [4.0.3](https://github.com/rsionnach/nthlayer-generate/compare/v4.0.2...v4.0.3) (2026-10-31)


### Bug Fixes

* keep apply -v progress off stdout in JSON mode (opensrm-f751) ([5f1ee1e](https://github.com/rsionnach/nthlayer-generate/commit/5f1ee1e482dce7d11b8da82556a1d0452c8fe0e0))
* keep apply -v progress off stdout in JSON mode (opensrm-f751) ([f973c0a](https://github.com/rsionnach/nthlayer-generate/commit/f973c0ac1199223bc475ff1088d8fb3ff47f8de1))


### Documentation

* apply --output json keeps progress and warnings off stdout (opensrm-f751) ([471b2a7](https://github.com/rsionnach/nthlayer-generate/commit/471b2a7298a1ccfc17b82138dd69839131abb712))

## [4.0.2](https://github.com/rsionnach/nthlayer-generate/compare/v4.0.1...v4.0.2) (2026-10-31)


### Bug Fixes

* send CLI logs to stderr so plan/apply JSON stdout parses (opensrm-iiay) ([2bb26b9](https://github.com/rsionnach/nthlayer-generate/commit/2bb26b9bd593c33fd5741e47b18b250db5b97a40))
* send CLI logs to stderr so plan/apply JSON stdout parses (opensrm-iiay) ([d76609d](https://github.com/rsionnach/nthlayer-generate/commit/d76609d3c76cedaba11c071649c82d82aa96c1c5))


### Documentation

* CLI warnings now print to stderr, DEBUG/INFO hidden unless -v (opensrm-iiay) ([aacc6f2](https://github.com/rsionnach/nthlayer-generate/commit/aacc6f291278dc5806f7d1df136cfe154cb10fee))

## [4.0.1](https://github.com/rsionnach/nthlayer-generate/compare/v4.0.0...v4.0.1) (2026-10-30)


### Bug Fixes

* one set of dashboard panels per dependency technology (opensrm-wo62.4.22) ([66841e9](https://github.com/rsionnach/nthlayer-generate/commit/66841e9a7dc52b25a9f8fbb04f921eeb4ea41ef3))
* port legacy assertions onto the manifest path; dedupe dashboard technology panels (opensrm-wo62.4.22) ([35edcd7](https://github.com/rsionnach/nthlayer-generate/commit/35edcd7c4e0fc3cf7cb8446fd00de0f906b24ea3))


### Documentation

* dashboard technology panels appear once per technology (opensrm-wo62.4.22) ([0c47795](https://github.com/rsionnach/nthlayer-generate/commit/0c47795a60a715baa5b8c62ae7b5e74cd0580fef))

## [4.0.0](https://github.com/rsionnach/nthlayer-generate/compare/v3.5.0...v4.0.0) (2026-10-30)


### ⚠ BREAKING CHANGES

* nthlayer_generate.specs no longer exports parse_service_file, ServiceContext or Resource, and the modules specs.parser, specs.environments, specs.environment_merger, specs.variable_substitution and specs.template are removed. Load any manifest format with nthlayer_common.manifest.load_manifest(path, environment=...). The ServiceContext/Resource dataclasses remain internal in specs.models (opensrm-wo62.4.20).
* removed nthlayer_generate.generators.generate_sloth_spec, nthlayer_generate.recording_rules.build_recording_rules (and the recording_rules.builder module), nthlayer_generate.orchestrator.ResourceDetector, generators.sloth.convert_to_sloth_slo, generators.alerts.generate_alerts_for_service / extract_dependencies, specs.helpers.infer_technology_from_name / TECH_KEYWORDS, loki.generator.generate_loki_alerts_for_service_file / extract_dependencies_from_resources, dashboards.builder_sdk.build_dashboard, dashboards.sdk_adapter.create_service_dashboard and dashboards.validator.extract_technologies / extract_custom_overrides. Use the *_from_manifest functions with nthlayer_common.manifest.load_manifest.
* nthlayer_generate.cli no longer exports validate_dashboard_command or list_intents_command, and the modules nthlayer_generate.cli.dashboard_validate, nthlayer_generate.cli.dependencies and nthlayer_generate.slos.dependencies are removed.

### Code Refactoring

* delete the legacy parse_service_file loader (opensrm-wo62.4.6) ([bae7693](https://github.com/rsionnach/nthlayer-generate/commit/bae7693045ff914ee57aa56efb74f3fb49882ea5))
* delete the legacy ServiceContext/Resource generator entry points (opensrm-wo62.4.6) ([ea3db85](https://github.com/rsionnach/nthlayer-generate/commit/ea3db853d8f266384a8b23225346675db9f741e0))
* delete the unwired dependencies and dashboard-validate commands (opensrm-wo62.4.6) ([b50469b](https://github.com/rsionnach/nthlayer-generate/commit/b50469b29e58aae9d4979db6e83da17ef6659cbe))


### Documentation

* 4.0.0 upgrade note and docs for the removed legacy stack (opensrm-wo62.4.6) ([f733dd3](https://github.com/rsionnach/nthlayer-generate/commit/f733dd30a05c6ec093a1938c1de75f144c7aa689))

## [3.5.0](https://github.com/rsionnach/nthlayer-generate/compare/v3.4.0...v3.5.0) (2026-10-29)


### Features

* validate loads legacy files through nthlayer-common (opensrm-wo62.4.19) ([62f52ec](https://github.com/rsionnach/nthlayer-generate/commit/62f52ecc65e688a5fbbb951d72e60b3873510176))
* validate loads legacy files through nthlayer-common (opensrm-wo62.4.19) ([480e519](https://github.com/rsionnach/nthlayer-generate/commit/480e5198d735f777786bcccf494e31b7114fe81e))

## [3.4.0](https://github.com/rsionnach/nthlayer-generate/compare/v3.3.0...v3.4.0) (2026-10-29)


### Features

* plan/apply detect from the ReliabilityManifest and use the manifest handlers (opensrm-wo62.4.5) ([895dd98](https://github.com/rsionnach/nthlayer-generate/commit/895dd98e2b9491165bab0e18f5256343fbcffc9b))
* plan/apply detect from the ReliabilityManifest and use the manifest handlers (opensrm-wo62.4.5) ([9d503f6](https://github.com/rsionnach/nthlayer-generate/commit/9d503f6fd78e1837111b2c09922b84d28ef0603b))


### Bug Fixes

* require nthlayer-common 5.8.0 (opensrm-wo62.4.5) ([79b6c07](https://github.com/rsionnach/nthlayer-generate/commit/79b6c07aeaaaa0be161b1553656f3af772765497))

## [3.3.0](https://github.com/rsionnach/nthlayer-generate/compare/v3.2.0...v3.3.0) (2026-10-29)


### Features

* move slo, validate-slo, ownership, setup-pagerduty, diff-envs onto nthlayer-common (opensrm-wo62.4.4) ([7e64f87](https://github.com/rsionnach/nthlayer-generate/commit/7e64f87295ff215e5388ea9970e16cbc4e81a364))


### Bug Fixes

* diff-envs classifies manifest fields by declared type (opensrm-wo62.4.4) ([de8dd2c](https://github.com/rsionnach/nthlayer-generate/commit/de8dd2c46d26efe405989af4811b57a9cfe66f3f))


### Code Refactoring

* move slo, validate-slo, ownership, setup-pagerduty, diff-envs onto nthlayer-common (opensrm-wo62.4.4) ([d47d796](https://github.com/rsionnach/nthlayer-generate/commit/d47d796a95c6e14a6355e2ab0808c33afa45f11b))

## [3.2.0](https://github.com/rsionnach/nthlayer-generate/compare/v3.1.1...v3.2.0) (2026-10-28)


### Features

* move *_from_manifest commands onto nthlayer-common (opensrm-wo62.4.3) ([98e1029](https://github.com/rsionnach/nthlayer-generate/commit/98e1029a77a4d5c56d5217d285716850c67246ee))
* read common 5.7.0's latency threshold and declared dependency technology (opensrm-wo62.4.3) ([a30232d](https://github.com/rsionnach/nthlayer-generate/commit/a30232ddae21718308a0b6dd3084d9e644232b1f))


### Bug Fixes

* deterministic dependency order; generate-slo reports model errors (opensrm-wo62.4.3) ([67dde7b](https://github.com/rsionnach/nthlayer-generate/commit/67dde7b3700a173af15b3a170842383b4f1a5234))


### Code Refactoring

* move *_from_manifest commands onto nthlayer-common (opensrm-wo62.4.3) ([b8f49b4](https://github.com/rsionnach/nthlayer-generate/commit/b8f49b4a1a61de3f436c7730cebc72fc9421cef2))

## [3.1.1](https://github.com/rsionnach/nthlayer-generate/compare/v3.1.0...v3.1.1) (2026-10-27)


### Bug Fixes

* require nthlayer-common 5.6.0; re-pin template-user goldens (opensrm-wo62.4.1) ([c47b808](https://github.com/rsionnach/nthlayer-generate/commit/c47b808d63b3bae3d3c3979abd80a316fcb4f0d7))
* require nthlayer-common 5.6.0; re-pin template-user goldens (opensrm-wo62.4.1) ([c0aaabc](https://github.com/rsionnach/nthlayer-generate/commit/c0aaabc6bbb5072f1e86724704e072b87761328a))

## [3.1.0](https://github.com/rsionnach/nthlayer-generate/compare/v3.0.0...v3.1.0) (2026-10-27)


### Features

* "Judgment thresholds" section in ai-gate api docs (opensrm-wo62.2) ([7f376b1](https://github.com/rsionnach/nthlayer-generate/commit/7f376b1bb210acadbdefd8e95c98a7b8ca5ac860))
* breach and not-evaluable alerts on judgment-threshold bounds (opensrm-wo62.2) ([35c7727](https://github.com/rsionnach/nthlayer-generate/commit/35c77279fc4f8a33fdb4e4d1d99760ccf5c58976))
* Brier and 30-day feedback-latency threshold recording rules (opensrm-wo62.2) ([e60c8e8](https://github.com/rsionnach/nthlayer-generate/commit/e60c8e89e74b69497d0a80dfe4c35497657bde49))
* judgment-threshold recording rules, alerts and docs (opensrm-wo62.2) ([3ecd05b](https://github.com/rsionnach/nthlayer-generate/commit/3ecd05b8ada6fb5ca2ba38b6a38fd87fd43d0520))

## [3.0.0](https://github.com/rsionnach/nthlayer-generate/compare/v2.1.2...v3.0.0) (2026-10-27)


### ⚠ BREAKING CHANGES

* nthlayer_generate.specs no longer exports load_manifest, ReliabilityManifest, SLODefinition or ManifestLoadError, and the modules specs.manifest, specs.loader and specs.opensrm_parser are removed. Import them from nthlayer_common.manifest. Every *_from_manifest function takes nthlayer_common's ReliabilityManifest. ContractRegistry.get_contract is replaced by get_contracts / promised_availability. srm/v1 SLOs declare PromQL under indicator.query; a top-level query is not read (opensrm-0i5h).

### Features

* **cli:** docs/backstage dry-run report common's ManifestLoadError (opensrm-wo62.1) ([1c84dc8](https://github.com/rsionnach/nthlayer-generate/commit/1c84dc897576daa773479efc9a4a0edbeb164850))
* consume nthlayer-common's manifest model; retire generate's own (opensrm-wo62.1) ([a705e5a](https://github.com/rsionnach/nthlayer-generate/commit/a705e5a9a5aa55f046db969311a4a9627a1507ff))
* **contracts:** compare v2 dependency expectations as ratios (opensrm-wo62.1) ([037b389](https://github.com/rsionnach/nthlayer-generate/commit/037b3894c585b538d396c07b3bc0af3f93ba59ab))
* **recording-rules:** judgment threshold rules from common's JudgmentThreshold (opensrm-wo62.1) ([3ff55c8](https://github.com/rsionnach/nthlayer-generate/commit/3ff55c8e16fe1524f8e5b70d0a648ae9f938017e))
* **specs:** generate-owned helpers over common's manifest model (opensrm-wo62.1) ([418050b](https://github.com/rsionnach/nthlayer-generate/commit/418050bed4ba72a57ae8bd9fa758c80c68d2ce81))


### Bug Fixes

* **migrate:** carry judgment thresholds into the migrated srm/v1 file (opensrm-wo62.1) ([db99e3c](https://github.com/rsionnach/nthlayer-generate/commit/db99e3c4d38b189217b04306453a916e28fbb09c))
* **migrate:** feedback_latency thresholds round-trip exactly; report srm/v1-incompatible SLOs (opensrm-wo62.1) ([21bdbea](https://github.com/rsionnach/nthlayer-generate/commit/21bdbead354b0c5ffe3a9e7715d46b9a5f8cc27e))
* **migrate:** no SLO type for judgment thresholds in migrated ai-gates (opensrm-wo62.1) ([c4c2d68](https://github.com/rsionnach/nthlayer-generate/commit/c4c2d68af540a45a760fba7b1b91baaae48e625f))
* **migrate:** write the SLO type so common loads migrated manifests (opensrm-wo62.1) ([e074fc0](https://github.com/rsionnach/nthlayer-generate/commit/e074fc01e3a34bcc5521acd438340afed3c06675))
* **sloth:** no malformed PromQL for latency SLOs without a query (opensrm-wo62.1) ([4d1ef8c](https://github.com/rsionnach/nthlayer-generate/commit/4d1ef8c28b8617f4b213e50f5950f80ebb8b203f))
* **validate:** narrow the TypeError catch to contract checks (opensrm-wo62.1) ([ee48f7d](https://github.com/rsionnach/nthlayer-generate/commit/ee48f7d968df85284b735e0f3651f94580e5f7f8))


### Dependencies

* require nthlayer-common 5.5.0 (opensrm-wo62.1) ([03071ba](https://github.com/rsionnach/nthlayer-generate/commit/03071ba2df1395c1d0e4a4c844f8432aaf185065))


### Documentation

* complete the 3.0.0 upgrade notes; golden update flag truthiness (opensrm-wo62.1) ([a946c88](https://github.com/rsionnach/nthlayer-generate/commit/a946c88c72ca33f61e6edb6bf908cb2ec1ed441a))
* generate reads manifests through nthlayer-common (opensrm-wo62.1) ([bb5a02f](https://github.com/rsionnach/nthlayer-generate/commit/bb5a02fbe3e3512de34c2ec2057894f2ca5046b2))

## [2.1.2](https://github.com/rsionnach/nthlayer-generate/compare/v2.1.1...v2.1.2) (2026-10-24)


### Dependencies

* require nthlayer-common 5.4.0 (opensrm-wo62.1) ([6b3b64d](https://github.com/rsionnach/nthlayer-generate/commit/6b3b64d699180d4476a039e19226867e4de3e5ef))


### Documentation

* document workers observe verify/portfolio/scorecard/check-deploy (opensrm-3ntg) ([4330fab](https://github.com/rsionnach/nthlayer-generate/commit/4330fabce5f1a17c47b3498f23b9c1180f994642))
* drop seven nonexistent commands and eleven undefined flags (opensrm-3ntg) ([c0d3872](https://github.com/rsionnach/nthlayer-generate/commit/c0d3872b916a4dfa64f008019c58148a53da6b5f))

## [2.1.1](https://github.com/rsionnach/nthlayer-generate/compare/v2.1.0...v2.1.1) (2026-10-23)


### Dependencies

* require nthlayer-common 5.3.1 (opensrm-dww5) ([6468d90](https://github.com/rsionnach/nthlayer-generate/commit/6468d9078e6e8ccd6f3fb9fed2c5920057c1a22a))

## [2.1.0](https://github.com/rsionnach/nthlayer-generate/compare/v2.0.7...v2.1.0) (2026-10-23)


### Features

* **cli:** migrate-manifest converts opensrm/v1 manifests (opensrm-pnmv) ([7991214](https://github.com/rsionnach/nthlayer-generate/commit/7991214d54dc948c44eac6995222431d6630de42))


### Dependencies

* require nthlayer-common 5.3.0 (opensrm-pnmv) ([0be7ab9](https://github.com/rsionnach/nthlayer-generate/commit/0be7ab9f664ed22bfd2f12402d98623cc734d081))

## [2.0.7](https://github.com/rsionnach/nthlayer-generate/compare/v2.0.6...v2.0.7) (2026-10-21)


### Dependencies

* require nthlayer-common 5.2.0 (opensrm-g35i) ([4b38cef](https://github.com/rsionnach/nthlayer-generate/commit/4b38cef24fbfacc26488d67962326dafe60891b9))

## [2.0.6](https://github.com/rsionnach/nthlayer-generate/compare/v2.0.5...v2.0.6) (2026-10-12)


### Dependencies

* require nthlayer-common 5.0.0 (opensrm-7zpz) ([27240e3](https://github.com/rsionnach/nthlayer-generate/commit/27240e3677d3bcb378b8422b7d7b6bc0dbd1cf56))

## [2.0.5](https://github.com/rsionnach/nthlayer-generate/compare/v2.0.4...v2.0.5) (2026-10-11)


### Bug Fixes

* **migrate:** migrate ai-gate srm/v1 judgment magnitudes to judgment_threshold (opensrm-tnz3) ([571087a](https://github.com/rsionnach/nthlayer-generate/commit/571087a2a70c50c667fc3fbeb6d0e620d1fcf560))


### Dependencies

* require nthlayer-common 4.0.0 (opensrm-tnz3) ([a520e4a](https://github.com/rsionnach/nthlayer-generate/commit/a520e4a9b7155f3aed367ae86d4820872186c950))

## [2.0.4](https://github.com/rsionnach/nthlayer-generate/compare/v2.0.3...v2.0.4) (2026-10-09)

### ⚠️ Behaviour changes in `nthlayer setup`

* **It now exits 1 when it fails.** Previously every failure printed an error
  and exited 0, so a CI step invoking `nthlayer setup` passed regardless. Any
  pipeline that relied on that will start failing — which is the point, but it
  will be a new failure.
* **It now writes `tier: critical|standard|low` instead of `tier: 1|2|3`.** The
  integer form was never accepted by `nthlayer validate`, so no valid manifest
  changes meaning; but a manifest generated by the wizard at 2.0.3 or earlier
  needs its `tier` field rewritten to the name. A deliberate skip (declining to
  create a service, or declining an overwrite) still exits 0.


### Bug Fixes

* **setup:** label the manifest encode handler as defensive and unreached (opensrm-h9fq) ([f08a9bd](https://github.com/rsionnach/nthlayer-generate/commit/f08a9bd597daf0ed95fa74d66e386ea86c4fa27c))
* **setup:** a failed write no longer truncates an existing manifest or removes a symlink (opensrm-h9fq) ([07a3ccf](https://github.com/rsionnach/nthlayer-generate/commit/07a3ccf6c88e11fc0ffb0cb401f8d737e4a540ab))
* **setup:** exit non-zero when the wizard fails (opensrm-h9fq) ([24c55de](https://github.com/rsionnach/nthlayer-generate/commit/24c55ded52a61769b5e378727c7f0974319ac8ba))
* **setup:** harden the write, mkdir and target check (opensrm-h9fq) ([81bf295](https://github.com/rsionnach/nthlayer-generate/commit/81bf2959ecff8198b024a685c8929a33a5143188))
* **setup:** quote the service name, which YAML retyped (opensrm-h9fq) ([00bb28f](https://github.com/rsionnach/nthlayer-generate/commit/00bb28fb636d9e9733617fcd228ca431dc8995a4))
* **setup:** stop the wizard writing a manifest validate rejects (opensrm-h9fq) ([8b3894e](https://github.com/rsionnach/nthlayer-generate/commit/8b3894e19aedef9938a4f28b74313dcaafc8d1a0))
* **setup:** a failed write no longer deletes an existing manifest (opensrm-h9fq) ([a1e5f6c](https://github.com/rsionnach/nthlayer-generate/commit/a1e5f6c2132f5afc702564312cc54d01df19d672))


### Documentation

* **setup:** correct the service-name rule's documentation (opensrm-h9fq) ([f5fc539](https://github.com/rsionnach/nthlayer-generate/commit/f5fc539973043b93f168a40c8b188fc029bcee16))
* **setup:** tidy stale comments around the shared name-rule table (opensrm-h9fq) ([cbb7776](https://github.com/rsionnach/nthlayer-generate/commit/cbb7776d243d8a1f79d7c55e93a284c2f8127a8e))
* **setup:** finish correcting the service-name rule's documentation (opensrm-h9fq) ([7956a1b](https://github.com/rsionnach/nthlayer-generate/commit/7956a1b9d97e08e212bba3855df2f2365cd2caa9))

## [2.0.3](https://github.com/rsionnach/nthlayer-generate/compare/v2.0.2...v2.0.3) (2026-10-09)


### Bug Fixes

* **init:** name only the characters the team guard actually rejects (opensrm-t4rd) ([da46bd4](https://github.com/rsionnach/nthlayer-generate/commit/da46bd4135eae6f527c4d9a96c81f27770539149))
* **init:** quote team values that YAML would retype (opensrm-t4rd) ([b8a2570](https://github.com/rsionnach/nthlayer-generate/commit/b8a2570acdd0053ccbd81467e3c13d39108835ce))
* **init:** quote the service name, which YAML retyped for no/yes/null (opensrm-t4rd) ([aa7cce7](https://github.com/rsionnach/nthlayer-generate/commit/aa7cce7e8da0ca8e1cee7c2e7c6ef748b49a6563))
* **init:** report a blank team as required, not as a control character (opensrm-t4rd) ([45dc02b](https://github.com/rsionnach/nthlayer-generate/commit/45dc02bed2fd4f063d4b58849aa2f0379703f1d0))
* **init:** stop corrupting non-BMP team names and crashing on 0b_ (opensrm-t4rd) ([062bb38](https://github.com/rsionnach/nthlayer-generate/commit/062bb3808559653023ce5da497beeca3412865cb))
* **init:** stop exiting 0 after writing a manifest that is wrong ([29ede75](https://github.com/rsionnach/nthlayer-generate/commit/29ede754445cc9bcf2a36e2509881ba56605d907))
* **init:** write manifests as UTF-8 and roll back a failed write (opensrm-t4rd) ([2b0f401](https://github.com/rsionnach/nthlayer-generate/commit/2b0f401908f062006f5f4a75b7fc11c0f0e9891f))


### Documentation

* **init:** correct stale cross-file claims around the scalar helpers (opensrm-t4rd) ([fb4c8a2](https://github.com/rsionnach/nthlayer-generate/commit/fb4c8a246e7d92b9e5f6dadae57d39fffd36840b))
* **init:** make the citation guard honest about its own reach (opensrm-t4rd) ([f40b0d8](https://github.com/rsionnach/nthlayer-generate/commit/f40b0d846528f39570e7ec2f9e7045d67a8591b4))

## [2.0.2](https://github.com/rsionnach/nthlayer-generate/compare/v2.0.1...v2.0.2) (2026-10-06)


### Documentation

* **deps:** section the comment so live policy is not filed as history ([bf3bfa6](https://github.com/rsionnach/nthlayer-generate/commit/bf3bfa680c20475890d5d17f75489356e457c020))
* **deps:** stop the floor rationale asserting a floor that moved ([1fd53fa](https://github.com/rsionnach/nthlayer-generate/commit/1fd53fae50cb5ff88c3bbfa3fa7971c763908c5a))

## [2.0.1](https://github.com/rsionnach/nthlayer-generate/compare/v2.0.0...v2.0.1) (2026-09-28)


### Bug Fixes

* bound the nthlayer-common range to the versions actually tested ([d749cce](https://github.com/rsionnach/nthlayer-generate/commit/d749cce37e0b31e85df18764bc944e91e4a7c164))
* bound the nthlayer-common range to the versions actually tested (opensrm-z7gn) ([461e887](https://github.com/rsionnach/nthlayer-generate/commit/461e887a2d7c03f229a587c664d72403d6eca175))
* close R5 correctness minors on the init doc guard (opensrm-noc6) ([c9748b4](https://github.com/rsionnach/nthlayer-generate/commit/c9748b42a37f8552493714ada63f9dfd449f6701))
* correct init doc drift and non-interactive UX (opensrm-noc6) ([9977697](https://github.com/rsionnach/nthlayer-generate/commit/99776970f25d64f0da4a54d3e0c41ab228e28c90))
* extend init doc/parser guard to reference/cli.md (opensrm-noc6) ([22f25de](https://github.com/rsionnach/nthlayer-generate/commit/22f25decb594d55b1fa1539f5c325fa30debe8c1))
* make the init menu the manifest service-type vocabulary (opensrm-8qpd) ([85efd2e](https://github.com/rsionnach/nthlayer-generate/commit/85efd2e39fbff05b2dffd210b37c065c34ca89f6))
* make the init menu the manifest service-type vocabulary (opensrm-8qpd) ([a8bfafd](https://github.com/rsionnach/nthlayer-generate/commit/a8bfafd92d5f46f3367c583cd2ef716a054917b0))
* wire --no-interactive on init and correct its docs (opensrm-noc6) ([e442cd8](https://github.com/rsionnach/nthlayer-generate/commit/e442cd8f0c649e424bd35a794da2d4406065ecb5))
* wire --no-interactive on init and correct its docs page (opensrm-noc6) ([6855d83](https://github.com/rsionnach/nthlayer-generate/commit/6855d83e450e35caae7a23661845cdfc18179c92))


### Documentation

* **tests:** state which half of rule 10 the container guard enforces ([4d54f95](https://github.com/rsionnach/nthlayer-generate/commit/4d54f95d77a373e40802fdec95fdb85fff407f8f))

## [2.0.0](https://github.com/rsionnach/nthlayer-generate/compare/v1.1.1...v2.0.0) (2026-08-27)


### ⚠ BREAKING CHANGES

* the `web` service type is now the OpenSRM extension type `x-web`. Existing manifests keep working — `web` resolves as an alias — but generated output changes: Backstage entity JSON, the plugin's ServiceContext['type'] union, the `type` label on Sloth rules, and manifests rewritten by `nthlayer migrate` all now carry `x-web`. Downstream consumers keying on `type="web"` must be updated; they will stop matching rather than error. `${type}` substitution deliberately keeps the authored spelling, since it targets pre-existing metrics. Requires nthlayer-common>=2.0.0.

### Features

* rename the web service type to the spec extension x-web (opensrm-z3ab) ([040bdaa](https://github.com/rsionnach/nthlayer-generate/commit/040bdaac405a1116069213a9e4622c60dc413a27))


### Bug Fixes

* carry authored_type across every construction path (opensrm-z3ab) ([2d0eda9](https://github.com/rsionnach/nthlayer-generate/commit/2d0eda9c2384b8b21350b61589cdf24401417a32))
* import service-type rule from nthlayer-common (opensrm-z3ab) ([d227a3b](https://github.com/rsionnach/nthlayer-generate/commit/d227a3bb109172bcbaa4c05dcedb7287e142cf7d))
* import service-type rule from nthlayer-common (opensrm-z3ab) ([494f9b6](https://github.com/rsionnach/nthlayer-generate/commit/494f9b6de087f28bff1d0223bc6c3a33a0c8320b))
* keep the authored spelling for ${type} substitution (opensrm-z3ab) ([8292d9c](https://github.com/rsionnach/nthlayer-generate/commit/8292d9c7f9e818bbbc3fcce227de371d566bf000))
* require nthlayer-common&gt;=2.0.0 (opensrm-z3ab) ([21ce3ab](https://github.com/rsionnach/nthlayer-generate/commit/21ce3ab65ff2c041d05f59377929c0b9d11adfc6))
* resolve service type once in init, restore template vocabulary (opensrm-z3ab) ([8352615](https://github.com/rsionnach/nthlayer-generate/commit/8352615bf2976ab988b1fb256d3ea99f503cc82c))


### Documentation

* correct the versioning policy and a stale field comment (opensrm-z3ab) ([5f8866a](https://github.com/rsionnach/nthlayer-generate/commit/5f8866a447fcd6f259de18b5afaa3af51cd377e4))
* document the real branching and release flow (opensrm-z9sz) ([698421a](https://github.com/rsionnach/nthlayer-generate/commit/698421a8f1aefae45165ebc1d345dccb6199d844))
* note where the resolved and authored spellings each belong (opensrm-z3ab) ([104ceb6](https://github.com/rsionnach/nthlayer-generate/commit/104ceb663e03c71992de9b66f66fe777ac985903))
* rewrite contributing guide (opensrm-tu04.4) ([#14](https://github.com/rsionnach/nthlayer-generate/issues/14)) ([7c8f621](https://github.com/rsionnach/nthlayer-generate/commit/7c8f6213864687c26e6f46842c29f04143f41354))
* trim fix-archaeology, fix a stale comment and a vacuous test (opensrm-z3ab) ([124e692](https://github.com/rsionnach/nthlayer-generate/commit/124e692565b5f9f516e6c72bc0280a26810c6b3c))

## [1.1.1](https://github.com/rsionnach/nthlayer-generate/compare/v1.1.0...v1.1.1) (2026-06-08)


### Bug Fixes

* **ci:** add tag-push + workflow_dispatch triggers to release.yml ([0beff7b](https://github.com/rsionnach/nthlayer-generate/commit/0beff7ba2bdae76c8208b13876d83e28907204dc))
* **ci:** move release smoke to tests/release-smoke/ (avoid collision) ([08185ac](https://github.com/rsionnach/nthlayer-generate/commit/08185acb937b1d091be956962e6a3fe67250980d))
* **lint:** autofix 23 ruff I001 import-order violations ([15c1dd2](https://github.com/rsionnach/nthlayer-generate/commit/15c1dd20f1c6c762e08ca6f8372e99eadec2cbf5))
* **tests:** set pythonpath=["src"] so pytest finds nthlayer_generate ([a6621e3](https://github.com/rsionnach/nthlayer-generate/commit/a6621e3a778245ec9461b8c66d38988a2c95e26d))


### Documentation

* **CLAUDE.md:** document release-please + smoke gate + Dependabot ([2146eb4](https://github.com/rsionnach/nthlayer-generate/commit/2146eb423018a21d31c2152fcc70595bc3fc01f4))
* link to ecosystem testing conventions (opensrm-2wkc) ([77a3411](https://github.com/rsionnach/nthlayer-generate/commit/77a341100b11882ab723768c1b35b933674bec6a))
* thin CLAUDE.md; defer to AGENTS.md + existing docs/ ([922d203](https://github.com/rsionnach/nthlayer-generate/commit/922d20397a6f8aa4727ec0e0e09021437454bff8))

## [1.1.0](https://github.com/rsionnach/nthlayer-generate/compare/v1.0.0...v1.1.0) (2026-05-10)


### Features

* **cli:** add `nthlayer migrate-manifest` for v1→v2 migration (P2-A.2) ([81fa10e](https://github.com/rsionnach/nthlayer-generate/commit/81fa10ed5e93a79f57afd13cc5068e9af62d4f18))


### Bug Fixes

* **slo:** distinguish None (no data) from 0.0 (total outage) in collect CLI ([895428e](https://github.com/rsionnach/nthlayer-generate/commit/895428ea02ae1924a3e07783ab353a2114af57c1))


### Code Refactoring

* **slo:** unconditional percentage-&gt;ratio at OpenSLO boundary ([66346b9](https://github.com/rsionnach/nthlayer-generate/commit/66346b96ec4568489cb55fc30f3981c72685a734))


### Documentation

* **CLAUDE.md:** consolidation refs + e1gk auto-memory updates ([89fb35a](https://github.com/rsionnach/nthlayer-generate/commit/89fb35af304c184a5c73410485919f2b0494aee7))
* **CLAUDE.md:** document migrate-manifest CLI ([82c230e](https://github.com/rsionnach/nthlayer-generate/commit/82c230efdedb2baee9bffc08f4b3d83c1ee4236a))
* **CLAUDE.md:** document unconditional OpenSLO boundary conversion ([aac90bc](https://github.com/rsionnach/nthlayer-generate/commit/aac90bce2a21ffe0f7cb56119ee57cf2c2c3c3e1))
* **claude:** repoint stale superpowers spec ref to nthlayer/ ([92b0a36](https://github.com/rsionnach/nthlayer-generate/commit/92b0a36c2ae34496f7a236600e8c8c6f1336a973))

## v0.1.0a18 (March 6, 2026)

### Build-Time Policy Engine

- **Policy engine core** (`policies/engine.py`, `policies/rules.py`, `policies/models.py`) — evaluate policies against service specs at build time
  - Required fields validation with dot-path resolution (e.g., `ownership.runbook`)
  - Tier constraint enforcement (min SLOs, deployment gates, ownership requirements)
  - Dependency rules (critical deps must have SLOs, max critical dep limits)
  - Central `policies.yaml` for org-wide defaults + per-service `PolicyRules` resource overrides
- **CLI integration** — `nthlayer validate --policies <policies.yaml>` for build-time policy evaluation
- **PolicyHandler** in orchestration system for evaluating `PolicyRules` resources during `apply`
- **SARIF rules** NTHLAYER009 (PolicyRequiredField), NTHLAYER010 (PolicyTierConstraint), NTHLAYER011 (PolicyDependencyRule)
- 63 new tests across 4 test files

### Quality Promotions

- **No D-grade or F-grade packages remain** — all packages at C or above
- `domain/` promoted to A-grade (100% coverage, fully documented)
- `core/`, `db/`, `identity/` promoted from C to B-grade
- `policies/` enters at B-grade (55 tests)
- 150+ new tests across promoted packages

### Topology Export

- `nthlayer topology export` command with JSON, Mermaid, and DOT output formats
- BFS-limited subgraph export with `--depth` and `--demo` flags
- Nord-themed styling for Mermaid and Graphviz output

### Enhanced Deploy Correlation

- 5-factor weighted scoring for deployment impact analysis (burn_rate, proximity, magnitude, dependency, history)
- Dependency-aware correlation and deployment blocking

### Service Documentation Generation

- `nthlayer generate-docs` produces README, ADR scaffold, and API docs from manifests

### CLI Smoke Test Harness

- Subprocess-level functional tests in `tests/smoke/`
- Pre-push hook runs smoke tests automatically

---

## v0.1.0a17 (February 27, 2026)

### Orchestrator Refactor

- **Phased orchestration package** (`orchestration/`) — split monolithic `ServiceOrchestrator` into modular components
  - `ResourceHandler` protocol and `ResourceRegistry` for pluggable resource types
  - `ExecutionEngine` for running generation loops with `ResultCollector` aggregation
  - `PlanBuilder` for previewing generation plans before execution
  - `ServiceOrchestrator` retained as backward-compatible facade

### Desloppify Code Quality Sweep

- **29 findings resolved** — structured logging enforcement, dead code removal, test coverage gaps
- Migrated `mock_server.py` to `tests/fixtures/`, added `conftest.py` for shared test config
- New `test_critical_models.py` and `test_verification.py` test suites
- Cleaned up demo files, renamed ad-hoc scripts to `try_` prefix
- Removed duplicate `cli/formatters/models.py`, consolidated SARIF formatter

### Deployment Detection

- **Provider-agnostic webhook handling** via `BaseDeploymentProvider` ABC
- ArgoCD, GitHub Actions, and GitLab CI/CD webhook parsers
- `DeploymentProviderRegistry` for self-registering providers
- HMAC SHA256 signature verification per provider
- FastAPI webhook endpoint: `POST /webhooks/deployments/{provider_name}`

### Policy Audit Logging

- **Immutable audit trail** for deployment gate decisions
- Domain models: `PolicyEvaluation`, `PolicyViolation`, `PolicyOverride`
- `PolicyAuditRecorder` and `PolicyAuditRepository` with fail-open error handling
- REST API: `POST /policies/{service}/override`, `GET /policies/{service}/audit`

### Harness Engineering Infrastructure

- Test harness and engineering tooling for reliability validation workflows

### Backstage Plugin

- Backstage plugin for NthLayer reliability data integration

### Alert Enhancements

- Grafana dashboard links added to alert rule annotations

### Bug Fixes

- Resolve 10 audit findings across error handling, validation, HTTP client, and metric resolution
- Lazy AWS imports (`aioboto3`, `boto3`) for CI environments without `[aws]` extras
- Skip `test_workers_handler.py` and `test_secrets.py` when `aioboto3` is not installed
- Defer SQS `JobEnqueuer` import to runtime in `api/deps.py`

### CI/CD

- MkDocs GitHub Pages workflow (`.github/workflows/docs.yml`)
- Lazy optional dependency imports via `__getattr__` pattern

---

## v0.1.0a16 (February 4, 2026)

### Intelligent Alerts Pipeline

- **`nthlayer alerts` command family** — evaluate, show, explain, test subcommands for alert management
- **AlertPipeline** — full pipeline evaluation against live or simulated budget data with notification support
- **AlertEvaluator** — rule resolution engine combining explicit and auto-generated alert rules per tier
- **ExplanationEngine** — context-aware budget explanations with technology-specific investigation actions
- **Alert simulation** — `nthlayer alerts test --simulate-burn 80` to preview what would fire at a given burn level
- **Multiple output formats** — table, JSON, YAML, and Markdown output for CI/CD integration
- Exit codes for CI/CD: 0=healthy, 1=warnings, 2=critical

### OpenSRM Phase 4: Contract & Dependency Validation

- **Contract registry** (`ContractRegistry`) — file-based registry that scans directories for manifest contracts, enabling cross-service validation (spec 11.3 Optional)
- **Dependency expectation validation** — warns when a dependency's expected availability exceeds the provider's published contract (spec 11.3 Recommended)
- **Transitive feasibility check** — warns when a service's contract availability is mathematically infeasible given its critical dependency chain (serial chain model, spec 11.3 Optional)
- **Template resolution** — OpenSRM templates are now resolved and deep-merged before parsing, with service-wins override semantics (spec 8.3)
- **Circular template detection** — templates that reference other templates are detected and warned about (spec 8.3.4 no-chaining rule, spec 11.2 Recommended)
- **Contract validation wired into validator** — `validate_service_file()` now runs `validate_contracts()` for OpenSRM files and accepts an optional `ContractRegistry` for cross-service checks
- **CLI `--registry-dir` flag** — `nthlayer validate --registry-dir <dir>` enables dependency and transitive feasibility validation against a directory of manifests
- **`metadata.template` passed through** in OpenSRM parser (previously parsed but not stored on manifest)

All new validation produces warnings (not errors) per spec Recommended/Optional priority.

#### Bug Fixes

- Fix policy evaluator parentheses regex matching function-call arguments

#### Dependencies

- Update rich from <14.0.0 to <15.0.0
- Update cachetools requirement
- Update mangum requirement
- Update python-json-logger requirement
- Update langchain from <0.4.0 to <1.3.0
- Resolve yanked numpy 2.4.0 in lockfile

#### CI

- Bump actions/checkout from 4 to 6
- Bump github/codeql-action from 3 to 4
- Bump peter-evans/create-pull-request from 5 to 8

---

## v0.1.0a15 (January 30, 2026)

### OpenSRM: Service Reliability Manifest Format

- **New format: `apiVersion: srm/v1`** - Declarative service reliability manifests
  - Unified `ReliabilityManifest` internal model that both OpenSRM and legacy NthLayer formats normalize to
  - OpenSRM YAML parser with validation for all spec sections
  - Format auto-detection loader — existing legacy files continue to work
  - Support for 7 service types: api, worker, stream, ai-gate, batch, database, web
  - AI gate services with judgment SLOs (reversal rate, calibration, feedback latency)
  - Deployment gates: error budget, SLO compliance, recent incidents
  - External contracts with internal SLO margin validation
  - Example manifests for all service types in `examples/opensrm/`

- **Generator migration to ReliabilityManifest** - All generators now accept both formats
  - `generate_alerts_from_manifest()` — alert generation from manifest
  - `generate_sloth_from_manifest()` — Sloth SLO spec generation from manifest
  - `ManifestDashboardBuilder` — Grafana dashboard generation from manifest
  - `generate_loki_alerts_from_manifest()` — Loki alert generation from manifest
  - `recommend_metrics_from_manifest()` — metric recommendations from manifest
  - Recording rules manifest builder adapter
  - Shared `extract_dependency_technologies()` helper consolidating duplicated logic
  - `ReliabilityManifest.as_service_context()` factory for backward compatibility

- **CLI migration to `load_as_legacy()` bridge** - All CLI commands now work with OpenSRM files
  - `load_as_legacy()` bridge function auto-detects format and routes to correct parser
  - OpenSRM files: `load_manifest()` → `as_service_context()` + `as_resources()`
  - Legacy files: direct `parse_service_file()` fallback for full compatibility
  - `ReliabilityManifest.as_resources()` converts SLOs, dependencies, and PagerDuty to Resource objects
  - All 17 CLI commands migrated (`validate`, `plan`, `generate-dashboard`, `generate-alerts`, etc.)
  - All generators, orchestrator, and portfolio aggregator migrated
  - `parse_service_file()` remains available for direct import (non-breaking)

- **`nthlayer migrate`** - CLI command to convert legacy format to OpenSRM

#### Bug Fixes

- Fix `recommend_metrics` returning `slo_ready=True` when no metric template found
- Add logging to sloth generator exception handlers (previously silent)
- Warn on invalid dependency criticality values in OpenSRM parser and legacy loader
- Fix dependency dashboard panels using application service name instead of exporter service name in PromQL queries (e.g. `service="postgresql"` instead of `service="payment-api"`)
- Fix intent resolution producing empty guidance panels when no MetricResolver configured; now uses first candidate metric name as fallback
- Fix gauge panels missing min/max; only set explicit max for percent/percentunit units
- Fix queue dependencies silently dropped in dashboard builder — Kafka, RabbitMQ, etc. now generate panels
- Fix validator rejecting legacy type aliases (`background-job`, `pipeline`)
- Add Redpanda as template alias for Kafka (wire-compatible)
- Fix `ServiceContext` type annotation in sloth `convert_to_sloth_slo`
- Remove unused `Contract` import from loader
- Fix f-strings without placeholders in OpenSRM parser
- Fix mypy type errors in sloth indicator dict and alerts routing argument

### Reliability Scorecard Calculator

- **`nthlayer scorecard`** - Per-service reliability scores (0-100)
  - Weighted score components: SLO Compliance (40%), Incident Score (30%), Deploy Success Rate (20%), Error Budget Remaining (10%)
  - Score bands: EXCELLENT (90+), GOOD (75-89), FAIR (50-74), POOR (25-49), CRITICAL (0-24)
  - Team aggregation with tier weighting (tier-1: 3x, tier-2: 2x, tier-3: 1x)
  - Output formats: table, json, csv
  - `--by-team` flag for team-level view
  - Exit codes for CI/CD: 0=excellent/good, 1=fair, 2=poor/critical
  - 36 tests with 100% coverage on core module

#### Dependencies

- Update httpx from <0.28.0 to <0.29.0
- Update pytest from <9.0.0 to <10.0.0
- Update respx from <0.22.0 to <0.23.0
- Update pytest-asyncio requirement

---

## v0.1.0a14 (January 18, 2026)

### CI/CD Proliferation, SLO Ceiling Validation & Metrics Recommendation Engine

This release adds three major features for production reliability enforcement.

#### New CLI Commands

- **`nthlayer recommend-metrics`** - Metrics recommendation based on service type
  - 7 service type templates: api, grpc, worker, queue-consumer, database-client, gateway, cache
  - Runtime-specific metrics: Python, JVM, Go, Node.js
  - Prometheus metric discovery with 50+ alias mappings
  - Integration with official `opentelemetry-semantic-conventions` package
  - `--check` flag to validate against live Prometheus
  - `--show-code` flag for instrumentation snippets

- **`nthlayer validate-slo-ceiling`** - SLO ceiling validation
  - Validates SLO targets don't exceed what dependencies can support
  - Calculates maximum achievable availability based on dependency SLAs
  - Warns when SLO targets are unrealistic given dependency constraints

#### CI/CD Integration

- **Output formatters** for CI/CD pipelines
  - GitHub Actions annotations (`--format github`)
  - GitLab CI reports (`--format gitlab`)
  - JSON output (`--format json`)
  - Quiet mode (`-q`) to suppress non-essential output

- **GitHub Action** workflow for automated validation
  - Ready-to-use action at `.github/actions/nthlayer-validate`

#### Internal

- Renamed `metrics.py` to `cloudwatch.py` to avoid module naming conflict
- Added `opentelemetry-semantic-conventions` as dependency
- 96% test coverage on the metrics module

---

## v0.1.0a13 (January 14, 2026)

### Alert Template Sync & Bug Fixes

This release adds automated alert template synchronization from the awesome-prometheus-alerts community repository, plus several bug fixes.

#### New Features

- **Alert Template Sync** - Automated synchronization from [awesome-prometheus-alerts](https://github.com/samber/awesome-prometheus-alerts)
  - `scripts/sync_awesome_alerts.py` - Sync script with auto-fix for common template bugs
  - New `AlertValidator` class for template validation and repair
  - Fixes label references, syntax issues, and common template errors
  - GitHub Action workflow for scheduled sync (`.github/workflows/sync-awesome-alerts.yml`)

#### Bug Fixes

- **Dashboard generation** - Fix `$service` variable replacement (now uses actual service name)
- **CLI** - Add `--prometheus-url` option to dashboard commands
- **Recording rules** - Align metric name with drift analyzer expectations
- **CLI version** - Use `importlib.metadata` for single source of truth

#### Internal

- Migrated issue tracking to proper `bd` CLI workflow
- Updated CLAUDE.md with beads usage documentation

---

## v0.1.0a12 (January 12, 2026)

### Phase 2 Complete: Dependency Intelligence & Service Discovery

This release completes Phase 2 (Dependency Intelligence) and Phase 2.5 (Service Discovery Providers), adding comprehensive service dependency analysis, ownership resolution, and multi-provider discovery.

#### New CLI Commands

- **`nthlayer identity`** - Service identity resolution and normalization
  - `identity resolve <name>` - Resolve service to canonical name
  - `identity list` - List known service identities
  - `identity normalize <name>` - Show normalization steps
  - `identity add-mapping` - Add custom identity mappings

- **`nthlayer ownership`** - Multi-source ownership attribution
  - Queries Backstage, PagerDuty, CODEOWNERS, Kubernetes labels
  - Confidence-based resolution when sources disagree
  - Shows on-call contact and escalation path

- **`nthlayer validate-slo`** - SLO metric existence validation
  - Validates SLO metrics exist in Prometheus before deployment
  - Checks recording rule dependencies
  - Label consistency validation

#### Enhanced Commands

- **`nthlayer deps`** - Now supports multiple providers
  - Backstage catalog integration
  - Kubernetes service discovery
  - Prometheus metric-based inference
  - DOT graph output format

- **`nthlayer blast-radius`** - Improved impact analysis
  - Multi-provider dependency traversal
  - Configurable depth analysis
  - Risk scoring with exit codes

#### New Dependency Providers (Phase 2.5)

- **Backstage** - Catalog API integration for service relationships
- **Kubernetes** - Service/Deployment label-based discovery
- **Consul** - Service catalog, health checks, Connect intentions
- **Zookeeper** - Curator-style service discovery
- **etcd** - Key-value prefix-based discovery

#### New Ownership Providers

- **Backstage** - `spec.owner` from catalog entities
- **PagerDuty** - Escalation policy owners, on-call schedules
- **Kubernetes** - `team`/`owner` labels on resources
- **CODEOWNERS** - GitHub/GitLab code ownership files
- **Declared** - Explicit `service.team` in service.yaml

#### Developer Experience

- **Pre-push hooks** - Tests run automatically before `git push`
- `make pre-commit-install` now installs both commit and push hooks
- `make setup` includes hook installation for new developers

#### Documentation

- New command documentation: deps, blast-radius, ownership, identity, validate-slo
- Updated CLI reference with all Phase 2 commands
- Dependencies section added to docs navigation

#### Stats Update

- **Tests:** 2821 passing
- **New CLI commands:** 4 (identity, ownership, validate-slo + subcommands)
- **Dependency providers:** 5 (Backstage, Kubernetes, Consul, Zookeeper, etcd)
- **Ownership providers:** 5 (Backstage, PagerDuty, Kubernetes, CODEOWNERS, declared)

---

## v0.1.0a11 (January 9, 2026)

### Security Release + Phase 1 & 2 Features

This release includes critical security fixes and two major feature phases.

#### Security Fixes
- **urllib3** CVE-2025-24810: Decompression-bomb bypass on redirects (2.6.2 → 2.6.3)
- **langgraph-checkpoint** RCE in JsonPlusSerializer (2.1.2 → 3.0.1 via langgraph 1.0)
- **ecdsa** Minerva timing attack: Removed entirely (python-jose → PyJWT migration)

#### Phase 1: Drift Detection
- **`nthlayer drift`** - Analyze SLO reliability trends over time
- Detects degradation, improvement, and oscillation patterns
- Statistical significance with confidence intervals
- Risk scoring based on pattern severity
- Demo mode with `--demo` flag

#### Phase 2: Dependency Intelligence
- **`nthlayer deps`** - Discover service dependencies from Prometheus metrics
- **`nthlayer blast-radius`** - Calculate deployment risk based on downstream dependents
- **Identity resolution module** - Service name normalization across providers
- Supports HTTP, gRPC, database, Redis, and Kafka dependency patterns
- Exit codes for CI/CD gates (0=low, 1=medium, 2=high risk)

#### Code Quality
- Test coverage expanded to 91% (2564 tests)
- Migrated from pip to uv for faster dependency management
- JWT authentication migrated from python-jose to PyJWT

---

## v0.1.0a10 (January 8, 2026)

### PyPI Release
- Version bump for PyPI publication
- No functional changes from a9

---

## v0.1.0a9 (January 7, 2026)

### Test Coverage & Core Improvements

#### Test Coverage
- Expanded test coverage from ~70% to 91%
- Added comprehensive tests for all CLI commands
- Integration tests for end-to-end workflows

#### Core Module
- New `src/nthlayer/core/` module for shared functionality
- Optimized orchestrator for better performance
- Improved configuration loading

#### Documentation
- Updated roadmap with 4-phase technical structure
- Simplified documentation structure

---

## v0.1.0a8 (December 21, 2025)

### Code Quality & CI/CD Improvements

#### Type Safety
- **Mypy errors fixed**: 142 → 0 type errors across all modules
- Full type annotation coverage in core modules

#### CI/CD Enhancements
- **Security scanning**: pip-audit for vulnerability detection
- **Dependabot integration**: Automated dependency updates
- **Pre-commit hooks**: ruff lint, mypy, pytest (pre-push)
- **Self-check validation**: NthLayer validates its own example specs

#### GitHub Actions Updates
- actions/checkout v4 → v6
- actions/cache v4 → v5
- actions/setup-python v5 → v6

#### Documentation
- **Architecture diagrams**: Mermaid diagrams with Iconify icons
- **Tech stack documentation**: Comprehensive module and component docs
- **Technology templates reference**: Exporter requirements and metrics documentation

#### Dependencies Updated
- ruff <0.5.0 → <0.15.0
- structlog 25.x → 26.x
- rich 14.x → 15.x
- mypy 1.11 → 1.20
- aioboto3 13.x → 16.x

#### CLI Fixes
- Questionary prompt styling improvements
- Service type to template mapping fix
- check-deploy latency SLO handling

---

## v0.1.0a7 (December 12, 2025)

### Reliability Shift Left - Major Release

This release establishes NthLayer as the **Reliability Shift Left** platform with comprehensive validation and deployment gates.

#### New Commands
- **`nthlayer verify`** - Contract verification: check declared metrics exist in Prometheus
- **`nthlayer validate-spec`** - OPA/Rego policy validation for service specs
- **`nthlayer validate-metadata`** - Prometheus rule metadata validation (labels, URLs)
- **`nthlayer check-deploy`** - Deployment gates based on error budget status

#### CLI First-Run Experience
- **Styled welcome message** when running `nthlayer` with no arguments
- Shows Quick Start commands, Key Commands, and documentation link
- ASCII banner with Nord colors in interactive terminals

#### Documentation Overhaul
- **Generate/Validate/Protect** structure for docs site
- New pages: CI/CD integration, Mimir support, deployment gates, shift-left concepts
- Nord color palette for docs site (dark/light mode)
- 5 new VHS demo GIFs

#### CI/CD Integration Examples
- GitHub Actions workflow
- GitLab CI template
- ArgoCD deployment gate hook
- Tekton pipeline task

#### Mimir Integration
- `nthlayer apply --push-ruler` supports Mimir/Cortex Ruler API
- Multi-tenant rule management

#### Policy Validation
- OPA/Rego policies for service specs (`policies/service.rego`, `slo.rego`, `dependencies.rego`)
- Conftest integration for CI/CD policy checks

---

## v0.1.0a6 (December 8, 2025)

### Complete CLI Styling with Nord Color Palette

- **New UX Module** (`src/nthlayer/cli/ux.py`) - Hybrid Charm/Rich module with Nord colors
- **ASCII Banner** - Blocky NTHLAYER banner on `--version` and no-command
- **Unicode Symbols** - Clean ✓✗⚠ℹ symbols instead of emojis (universal terminal support)
- **Nord Color Palette** - Frost blue headers, Aurora success/warning/error, Snow Storm muted text
- **Environment-Aware** - Detects CI/CD, respects NO_COLOR/FORCE_COLOR standards
- **Rich Tables** - Colored tables for portfolio and validation output
- **Styled All 19 Commands** - Consistent styling across entire CLI

### Demo GIFs
- Hero GIF with ASCII banner
- All 4 demo GIFs regenerated with new styling

---

## v0.1.0a2 (December 5, 2025)

### Code Quality - DRY Cleanup (~3,860 lines removed)
- **Phase 1**: Removed duplicate dashboard builders (`builder.py` → `builder_sdk.py`) and 6 legacy template files (~2,900 lines)
- **Phase 2**: Extracted secret backends to plugin system with lazy loading (~90 lines net reduction)
- **Phase 3**: Removed deprecated reslayer demo functions (~869 lines)

### New Features
- **SLO Portfolio command** - `nthlayer portfolio` for org-wide reliability view
- **Portfolio health scoring** - Tier-based weighting (tier-1: 3x, tier-2: 2x, tier-3: 1x)
- **Portfolio insights** - Actionable recommendations for SLO improvements

### Roadmap Updates
- Added Loki integration to roadmap (Phase 2.5)
- Added AI/ML service templates to roadmap
- Updated positioning: complementary to PagerDuty (not competitive)

### Improvements
- Modular secrets package with lazy-loaded cloud backends
- Faster startup (cloud backends only imported when needed)
- Cleaner CLI without redundant commands

---

## v0.1.0a1 (December 3, 2025)

Initial alpha release with core functionality.

---

## Pre-release

### Phase 4: PagerDuty Integration (December 2025)

### Complete PagerDuty Integration
- **Tier-based escalation policies** - Critical (5/15/30min), High (15/30/60min), Medium (30/60min), Low (60min)
- **Auto-creates resources** - Teams, Schedules (primary/secondary/manager), Escalation Policies, Services
- **Team membership** - API key owner automatically added as team manager
- **Support models** - self, shared, sre, business_hours with routing labels
- **Event Orchestration** - Alert routing for shared/sre support models
- **Alertmanager config** - Auto-generated with PagerDuty receiver, tier-based timing
- **Official SDK** - Uses `pagerduty.RestApiV2Client` (not bespoke HTTP client)
- **Resilient setup** - Continues creating resources even if some fail
- 38+ tests for PagerDuty and Alertmanager modules

### CLI Improvements
- Clean one-line per resource type output
- Verbose mode (`--verbose`) for file list and details
- Warnings grouped at end
- Removed cluttery box drawing

### Phase 3: Observability Suite (December 2025)

### Phase 3D: Polish & Documentation
- Added dashboard customization (--full flag for 28+ panels)
- Created comprehensive observability guide (500 lines)
- Updated README and presentations
- 84/84 tests passing

### Phase 3C: Recording Rules
- Implemented Prometheus recording rules generation
- 20+ pre-computed metrics per service
- CLI command: `generate-recording-rules`
- 10x dashboard performance improvement

### Phase 3B: Technology Templates
- Created 4 technology templates (40 panels total)
- PostgreSQL (12 panels), Redis (10), Kubernetes (10), HTTP/API (8)
- Template registry system
- Dashboards improved from 6 → 12 → 28 panels

### Phase 3A: Dashboard Foundation
- Implemented Grafana dashboard generation
- Dashboard models and builder
- CLI command: `generate-dashboard`
- 6-12 panels per service with SLO, health, and technology metrics

### Weeks 7-8: Multi-Environment Support

- Multi-environment configuration system (dev, staging, prod)
- Environment-specific overrides
- Auto-detection from 12+ CI/CD sources
- Variable substitution (${env}, ${service}, ${team})
- CLI commands: `list-environments`, `diff-envs`, `validate-env`

### Weeks 1-6: Foundation

### Alert Generation
- 400+ battle-tested alert rules from awesome-prometheus-alerts
- Auto-generated alerts for PostgreSQL, Redis, MySQL, MongoDB, Kafka, etc.
- CLI command: `generate-alerts`

### Core Features
- SLO generation from service specifications
- PagerDuty integration with auto-service creation
- Prometheus integration for error budget tracking
- Deployment correlation and gates
- Custom template system
- CLI with 10 commands

## Stats

- **Commands:** 30+ total
- **Tests:** 3,364 passing
- **Documentation:** 30,000+ words
- **Dashboard Panels:** 50+ in template library
- **Alert Rules:** 580+
- **Technology Templates:** 21 technologies supported
