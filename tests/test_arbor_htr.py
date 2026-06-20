import os
import json
import pytest
from unittest.mock import patch, AsyncMock
from app.tools.research_profiles import get_profile
from app.tools.research_engine import (
    arbor_ideate_hypotheses,
    arbor_select_hypotheses,
    arbor_evaluate_hypothesis_node,
    arbor_backpropagate_and_decide,
    render_arbor_tree_ascii
)

def test_arbor_htr_profile_registration():
    """Verify the arbor_htr research profile is correctly registered and configured."""
    profile = get_profile("arbor_htr")
    assert profile is not None
    assert profile["name"] == "🌲 Arbor HTR"
    assert "write_script" in profile["allowed_actions"]
    assert "arbor_htr" in profile["process_template"]

def test_arbor_select_hypotheses():
    """Verify that selection favors higher priority nodes while maintaining diversity."""
    tree = {
        "nodes": {
            "node_1": {"id": "node_1", "status": "pending", "priority": 0.9},
            "node_2": {"id": "node_2", "status": "pending", "priority": 0.2},
            "node_3": {"id": "node_3", "status": "merged", "priority": 0.8}
        }
    }
    # Should only select pending nodes (node_1 and node_2)
    selected = arbor_select_hypotheses(tree, n=1)
    assert len(selected) == 1
    assert selected[0]["id"] in ["node_1", "node_2"]

@pytest.mark.asyncio
async def test_arbor_ideate_hypotheses():
    """Verify coordinator can ideate and parse new hypotheses."""
    mock_llm_response = """
[
  {
    "hypothesis": "Verify price differences on Kraken vs Binance",
    "reason": "Test cross-exchange correlation",
    "priority": 0.85,
    "expected_actions": ["web_search", "fetch_market_data"]
  }
]
"""
    tree = {
        "root": {"score": 0.5, "insight": "Initial"},
        "nodes": {}
    }
    
    async def fake_llm_call(prompt, provider, model):
        return mock_llm_response

    new_nodes = await arbor_ideate_hypotheses(
        query="Forex pricing",
        tree=tree,
        llm_call=fake_llm_call
    )
    assert len(new_nodes) == 1
    assert new_nodes[0]["hypothesis"] == "Verify price differences on Kraken vs Binance"
    assert new_nodes[0]["priority"] == 0.85
    assert new_nodes[0]["status"] == "pending"

@pytest.mark.asyncio
async def test_arbor_evaluate_hypothesis_node():
    """Verify evaluator structure and multi-criteria scoring."""
    mock_llm_response = """
{
  "coverage": 0.9,
  "depth": 0.8,
  "reliability": 0.7,
  "coherence": 0.9,
  "recency": 0.8,
  "insight": "Kraken price feed is highly correlated with Binance.",
  "gaps": ["No historical check"]
}
"""
    node = {
        "hypothesis": "Test feed correlation",
        "reason": "Verify overlap",
        "evidence": [{"title": "Feed Info", "snippet": "Binance uses WS", "source": "web"}],
        "artifact": "print('OK')"
    }
    
    async def fake_llm_call(prompt, provider, model):
        return mock_llm_response

    eval_res = await arbor_evaluate_hypothesis_node(
        query="Forex pricing",
        node=node,
        llm_call=fake_llm_call
    )
    assert eval_res["scores"]["coverage"] == 0.9
    assert eval_res["overall"] > 0.7
    assert "gaps" in eval_res
    assert eval_res["insight"] == "Kraken price feed is highly correlated with Binance."

def test_arbor_backpropagate_and_decide():
    """Verify merge gate decision and backpropagation up the tree."""
    tree = {
        "root": {
            "score": 0.6,
            "insight": "Initial findings",
            "evidence": [],
            "assets": []
        },
        "nodes": {
            "node_1": {
                "id": "node_1",
                "parent_id": "root",
                "hypothesis": "Test regional prices",
                "status": "active",
                "score": 0.85,
                "scores_detail": {"coverage": 0.9},
                "insight": "Success insight",
                "evidence": [{"title": "Found prices", "url": "https://price.com"}],
                "assets": [{"name": "prices.json"}],
                "artifact": "data = 42"
            },
            "node_2": {
                "id": "node_2",
                "parent_id": "root",
                "hypothesis": "Test bad API",
                "status": "active",
                "score": 0.35,
                "insight": "Failed insight"
            }
        }
    }
    
    # Test merge scenario (node_1 score 0.85 > root 0.6)
    status_1, log_1 = arbor_backpropagate_and_decide(tree, "node_1", merge_gate_threshold=0.7)
    assert status_1 == "merged"
    assert tree["root"]["score"] == 0.85
    assert len(tree["root"]["evidence"]) == 1
    assert len(tree["root"]["assets"]) == 1
    assert "data = 42" in tree["root"]["artifact"]
    
    # Test prune scenario (node_2 score 0.35 < 0.45)
    status_2, log_2 = arbor_backpropagate_and_decide(tree, "node_2", merge_gate_threshold=0.7)
    assert status_2 == "pruned"

def test_render_arbor_tree_ascii():
    """Verify ASCII tree generation includes statuses and scores."""
    tree = {
        "root": {"score": 0.85, "insight": "Distilled info"},
        "nodes": {
            "node_1": {"hypothesis": "Hypothesis 1", "status": "merged", "score": 0.85, "parent_id": "root"},
            "node_2": {"hypothesis": "Hypothesis 2", "status": "pruned", "score": 0.35, "parent_id": "root"}
        }
    }
    ascii_str = render_arbor_tree_ascii(tree)
    assert "🌲 Hypothesis Tree Structure:" in ascii_str
    assert "🟢 Merged" in ascii_str
    assert "🔴 Pruned" in ascii_str
    assert "node_1" in ascii_str
