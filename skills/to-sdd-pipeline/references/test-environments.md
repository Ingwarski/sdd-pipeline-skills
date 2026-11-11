# Virtual-first test environments

Default to automated virtual environments, locally or in CI. A supported phone, tablet or desktop names product scope, not a requirement to obtain physical hardware. Select the smallest source-backed set of environments that covers distinct claims; do not multiply every check by device models, browsers and operating systems.

| Claim | Preferred execution |
|---|---|
| Responsive web layout and input | Browser automation with representative viewport/touch settings; add supported engines only for relevant differences. |
| iOS/iPadOS platform behavior | Xcode Simulator when browser emulation cannot exercise the required OS/API behavior. |
| Android platform behavior | Android Emulator with a suitable virtual device/API level. |
| Windows or other desktop OS behavior | Matching OS CI runner, such as GitHub Actions, or a VM with the required runtime/session. |

These are alternatives by claim, not a mandatory matrix. Browser device presets emulate selected properties; they do not run the named device's OS. Record the actual OS/runtime, engine, version, settings, execution and limitations. A CI badge alone proves no behavior; an unsuitable runner/session needs another virtual environment.

Executing product code, real storage or real integration boundaries in a simulator/VM is runtime evidence for the behavior observed. Mocked outcomes and design prototypes remain simulations. Do not relabel virtual evidence as physical-device, production-deployment or hardware-performance evidence.

Require physical-device testing only when an explicit user or governing project requirement calls for it. General platform support, accessibility, persistence or “native” wording alone does not. If a required hardware-specific outcome cannot be reproduced virtually, name that exact evidence gap and route the test-method or scope decision to its owner; do not invent a hardware matrix or mark it passed. An unresolved required claim blocks only the completion/release gates that depend on it.

For existing projects, reconcile affected architecture, DoD and QA definitions through their owners in an authorized project session. Preserve original results and valid acceptance; changing the default neither converts old observations nor silently waives an explicit hardware requirement. Installing the skillset never edits consumer projects or their evidence.
