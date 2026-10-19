# Twilio Voice AI project story and hands-on workshop

This is a **demo/MVP for learning how a Twilio Voice AI application works end to end**. The existing Maya course project uses a mock clinic, synthetic data, and an ElevenLabs voice shell. Its Twilio ConversationRelay phone path was deferred; the Twilio adapter and reliability exercises here are proposed additions. The senior-engineer story explains how to reason about a production-style version, without claiming real customer results, a senior title, or ownership of Twilio's platform.

## Read in this order

1. [Project story](project-story.md): business problem, product scope, senior engineer ownership, architecture, decisions, and outcomes to measure.
2. [Technical map and workshop](workshop.md): categories, actual repository anchors, ordered build, and the one active exercise.
3. [Interview practice](interview-practice.md): answer outlines and the compound timeout/interruption/transfer scenario.
4. [Official-source research](official-research.md): product and protocol facts, with direct links to Twilio documentation.
5. [Production voice AI research](industry-practice-research.md): cross-vendor guidance for answering caller questions, handling follow-ups, and measuring quality. It does not rely on the demo implementation.

The existing [codebase walkthrough](../codebase-walkthrough/README.md) is useful background for the agent, identity, scheduling, and admin layers. This workshop focuses on the additional Twilio call path and its failure semantics.

## Evidence labels

- **Existing:** directly visible in this repository at commit `86790fe` (checked October 14, 2026). The checkout has unrelated local edits; this workshop does not alter them.
- **Twilio documented:** a claim linked to official Twilio documentation.
- **Proposed:** a design or exercise to build and verify.
- **Illustrative:** the mock business situation or a production-design scenario, never a resume claim.
