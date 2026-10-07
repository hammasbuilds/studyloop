# Motion research and decisions

Method note: WebFetch on the Material and Apple pages returned only page titles (they are client-rendered), so the
numbers below for those two are the published spec values as I know them, and are marked as such. The Duolingo
findings come from a web search.

## What the references say

| Source | Finding used |
|---|---|
| [Material Design 3 easing and duration](https://m3.material.io/styles/motion/easing-and-duration/tokens-specs) (spec values) | Standard easing `cubic-bezier(.2,0,0,1)`, emphasized-decelerate `(.05,.7,.1,1)` for entering things, emphasized-accelerate `(.3,0,.8,.15)` for leaving things. Short durations 50-200 ms for small controls, medium 250-400 ms for panels. |
| [Apple HIG: Motion](https://developer.apple.com/design/human-interface-guidelines/motion) (principles) | Motion must have purpose (feedback, hierarchy), stay brief, never be the only signal, and honour Reduce Motion with an alternative visual cue. |
| [Duolingo microinteractions](https://60fpsdesign.substack.com/p/fun-in-every-frame), [overview](https://blakecrosley.com/zh-Hant/guides/design/duolingo) | Correct answer lights up and celebrates, wrong answer gets a gentle shake rather than a harsh error; confetti marks milestones; chunky buttons press down. StudyLoop already had the pressed-down button, so that stays. |
| Notion / Brilliant (observed) | Quiet hover tints at 120-200 ms; delight reserved for completion moments. |

## Numbers adopted

- Tokens: `--dur-fast 120ms`, `--dur-base 200ms`, `--dur-slow 320ms`; `--ease-std (.2,0,0,1)`, `--ease-out (.05,.7,.1,1)`, `--ease-spring (.3,1.5,.5,1)` for pops.
- Press scale .97, card hover lift 3px, tilt max 3 degrees, spotlight follows the pointer (fine pointers only).
- Stagger 45 ms per item, capped at 8. Count-up 700 ms. Confetti 900-1400 ms: 14 particles for a correct answer, 50 for mastery or a perfect round.
- Animate transform and opacity; SVG ring stroke offset and bar width keep their existing transitions.

## How taste is kept

Delight is limited to two moments: a small burst on a correct answer and a big one on mastery or a perfect round.
Everything else is feedback under 320 ms. With `prefers-reduced-motion` all movement is removed; colour and state
changes (focus ring, right/wrong tints, toast visibility) remain.
