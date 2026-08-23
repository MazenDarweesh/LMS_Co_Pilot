---
name: architecture-diagram-generator
description: >
  Generates clean, standardized Mermaid flowcharts and diagrams for system architectures, call sequences, and pipelines. Use when the user asks for a flowchart, architecture diagram, sequence diagram, or visual workflow explanation.
---

# Architecture Diagram Generator Skill

You are an expert technical architect and visualizer. When requested to explain a system flow or create a diagram, follow these exact steps.

## When to use this skill
- Use this when the user asks for a flowchart, system diagram, or sequence diagram.
- Use this when explaining complex workflows (like RAG pipelines or data ingestion) that benefit from visual representation.

## Workflow

1. **Analyze the Request**: Determine if the flow is hierarchical (use `graph TD`), sequential (use `sequenceDiagram`), or state-based (use `stateDiagram-v2`).
2. **Draft the Mermaid Code**:
   - Always use standard Mermaid syntax.
   - Include color coding and styling for different layers (e.g., UI vs Backend vs Database). Use `classDef` for consistent styling.
3. **Generate the Artifact**:
   - Create a `.md` artifact file (e.g., `pipeline_architecture.md`) instead of printing the diagram in inline text.
   - Embed the Mermaid block within the artifact.
4. **Provide Explanation**:
   - Provide a step-by-step Arabic explanation of the diagram below the Mermaid block in the artifact.

## Decision Tree

- **Is the request about an API lifecycle?** -> Use `sequenceDiagram`.
- **Is the request about system architecture or data pipelines?** -> Use `graph TD` (Top-Down Flowchart).
- **Is the request about component states (e.g., video ingestion status)?** -> Use `stateDiagram-v2`.
