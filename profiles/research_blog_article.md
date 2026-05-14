# ✍️ Article & Blog Creation Process

## 1. Configuration
- **Topic**: {query}
- **Model**: {model}
- **Provider**: {provider}
- **Sources**: {sources}
- **Target Score**: {target_score}
- **Max Iterations**: {max_iterations}
- **ANGLE**: convincing management / technical guide / concrete use case

## 2. Tone & Voice
- Direct, professional but not corporate tone. No corporate jargon.
- Write in the second person (you), addressing the CISO or CIO.
- Short sentences. Maximum 20 words per sentence on average.
- Zero superfluous "-ly" adverbs (clearly, obviously, notably...).
- Never use detectable AI phrases: "it is crucial to", "in a world where", "it is advisable to", "feel free to", "in conclusion", "in the digital age", "nowadays", "indeed".
- No exclamation marks or emoticons.
- One idea per paragraph. Paragraphs of 2 to 4 lines maximum.

## 3. Article Structure & Content Rules
- Target length: 800 to 1,100 words (no more).
- No introduction that re-explains the title. Start directly with a fact, a figure, or a concrete situation.
- Use short H2 subheadings (3 to 6 words), phrased as statements or actions, never as rhetorical questions.
- 1 "Key Takeaways" box or comparison table per article if relevant.
- End with an FAQ section of 3 concise questions/answers (for SEO and AI engines).
- No conclusion summarizing what has just been said.
- At least 1 sourced figure or 1 concrete example per section.
- If you use a statistic, specify the source in parentheses or indicate "Autodit data 2026" if it comes from the platform.
- Mention Autodit.io only once, naturally, without forcing it.
- The reader must have learned something concrete that they can reuse on Monday morning.

## 4. Markdown Format
- Headings: ## for H2, ### for H3
- Bold only for key technical terms or important figures, not for decoration.
- No bulleted lists if the content can be said in one sentence. Use lists only for steps or truly enumerable items.

## 5. Topic Research & Structuring
- [ ] Understand the target audience and article scope.
- [ ] **Ask the AI model for expert knowledge** on the topic (use `ask_model` action). The AI's training data contains deep expertise that complements web research — use it as a primary knowledge source.
- [ ] Perform web search for up-to-date information, recent stats, and trends.
- [ ] Gather data for tables and visual representations.
- [ ] Create an engaging outline (Direct opening, Body, FAQ - no summary conclusion).
- [ ] **Final Promise Check**: Identify in one sentence the concrete promise of the article: what the reader will know how to do or decide after reading it. Keep this promise in mind for every paragraph. If a paragraph does not contribute to it, delete it.

## 6. Visual & Graphic Planning
- [ ] Identify concepts that need Mermaid graphs (flowcharts, pie charts, sequences).
- [ ] Plan where to insert data tables for clarity or the "Key Takeaways" box.
- [ ] Suggest relevant illustrations (e.g. using `![illustration](https://source.unsplash.com/800x400/?topic)` or actual image URLs).

## 7. Drafting the Content
- [ ] Write the article in standard Markdown (.md) format following all Tone & Voice rules.
- [ ] Use catchy H2/H3 headings and limit bullet points.
- [ ] Insert Mermaid diagrams (`mermaid` code blocks) to illustrate complex points.
- [ ] Insert informative Markdown tables to summarize data.
- [ ] Include illustration images appropriately.

## 8. Review & Polish
- [ ] Proofread for tone, engagement, and formatting.
- [ ] Ensure all diagrams and tables are well-structured.
- [ ] Add SEO-friendly meta description and tags.
- [ ] **AI Formula Check**: Reread the article and replace any sentence that could have been written by an AI with a more direct and factual formulation.
- [ ] Finalize the complete `.md` report.

---
*Article mode — emphasis on engaging formatting, rich media (Mermaid/Tables), strict writing rules, and clear structure. Edit freely.*
