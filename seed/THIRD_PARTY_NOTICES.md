# Third-party sources of the seed packs

Most packs here hold lessons from my own projects. Some draw on guidance others published.
Every such lesson names its source in `found_by`. The lessons restate that guidance in their
own words; none copies a source's text. The sources and their licenses are listed below,
with the notices their licenses ask to be kept.

| Pack | Source | License |
|---|---|---|
| `test-quality` | [dotnet/skills](https://github.com/dotnet/skills), `plugins/dotnet-test/skills/test-anti-patterns` | MIT, Copyright (c) .NET Foundation and Contributors |
| `ci-security` | [getsentry/skills](https://github.com/getsentry/skills), `skills/gha-security-review` | Apache License 2.0 |
| `ci-security` | [trailofbits/skills](https://github.com/trailofbits/skills), `plugins/agentic-actions-auditor` | CC BY-SA 4.0: cited, not adapted (see below) |
| `react-defects` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills), `skills/react-best-practices` | MIT, as the skill's own front matter declares |
| `python-canon` | PEPs, the Python docs, and the tool and style-guide docs its `_comment` names | each source's own terms; cited, not copied |

**Trail of Bits.** CC BY-SA 4.0 would make an adaptation of their text ShareAlike. The
`ci-security` lessons that cite their auditor state the attack paths it names in my own
words, and copy none of its text. Attack techniques are facts, and the license covers only
the text that describes them.

**Apache 2.0.** The license text is at https://www.apache.org/licenses/LICENSE-2.0. The
`getsentry/skills` repository has no NOTICE file to carry.

## MIT notice (dotnet/skills)

Copyright (c) .NET Foundation and Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
