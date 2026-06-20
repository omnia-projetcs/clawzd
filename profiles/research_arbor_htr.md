# 🌲 Arbor Hypothesis-Tree Refinement Process

## 1. Configuration
- **Profile ID**: arbor_htr
- **Topic**: {query}
- **Model**: {model}
- **Provider**: {provider}
- **Sources**: {sources}
- **Target Score**: {target_score}
- **Max Iterations**: {max_iterations}

## 2. Hypothesis-Tree Initialization
- [ ] Initialize Root Hypothesis based on initial query
- [ ] Create initial node in the persistent tree structure
- [ ] Set root node status to active

## 3. Coordinator Loop
- [ ] **Observe**: Analyze current tree frontier, success/failure logs, and insights
- [ ] **Ideate**: Generate targeted child hypotheses to fill gaps or overcome failures
- [ ] **Select**: Choose pending nodes using exploration-friendly softmax selection
- [ ] **Dispatch**: Test selected hypotheses using executors in isolated worktrees
- [ ] **Backpropagate**: Update nodes with logs, scores, and distilled causal lessons
- [ ] **Decide**: Prune low-performing branches or merge improvements passing the merge gate

## 4. Isolated Executor Sandbox
- [ ] Create isolated workspace subdirectory `/worktrees/node_<id>` per node
- [ ] Execute research tasks (web search, smart scrape, script run) under isolation
- [ ] Prevent shared state contamination between different hypothesis branches

## 5. Causal Backpropagation
- [ ] Score each executor branch on 5 axes (coverage, depth, reliability, coherence, recency)
- [ ] Lift lessons learned from failure nodes up the path to guide coordinator ideation
- [ ] Prevent repetitive search spirals or metric-chasing behaviors

## 6. Merge Gate Evaluation
- [ ] Compare branch score against parent node score
- [ ] Run a held-out merge gate validator to ensure generalized improvements
- [ ] Merge accepted branch findings and artifacts into the root research state

## 7. Comprehensive Report
- [ ] Compile the final report from the merged root node state
- [ ] Include Mermaid visualizations of the hypothesis tree and branch paths
- [ ] Generate standard inline citations [1][2] and bibliography

---
*Arbor HTR mode — hypothesis-tree refinement with coordinator-executor isolation. Edit freely.*
