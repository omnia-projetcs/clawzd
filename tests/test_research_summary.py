from app.tools_research import _build_project_summary


def test_project_summary_counts_sources_assets_actions_and_report():
    project = {
        "id": "research_1",
        "title": "Market scan",
        "query": "fast battery startups",
        "status": "completed",
        "current_score": 0.82,
        "target_score": 0.75,
        "max_iterations": 4,
        "search_results": [
            {
                "title": "First result",
                "url": "https://www.example.com/a",
                "source": "web",
                "snippet": "Alpha",
            },
            {
                "title": "Duplicate result",
                "url": "https://www.example.com/a",
                "source": "web",
                "snippet": "Duplicate",
            },
            {
                "title": "News result",
                "url": "https://sub.example.org/b",
                "source": "news",
                "snippet": "Beta",
            },
            {
                "title": "Local note",
                "url": "",
                "source": "note",
                "snippet": "Gamma",
            },
        ],
        "assets": [
            {"name": "one.pdf", "type": "pdf", "size": 1024},
            {"name": "chart.png", "type": "png", "size": 2048},
        ],
        "iterations": [
            {
                "num": 1,
                "score": 0.4,
                "actions": [{"type": "web_search"}, {"type": "scrape"}],
                "completed_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "num": 2,
                "score": 0.82,
                "actions": [{"type": "web_search"}],
                "completed_at": "2026-01-01T00:10:00+00:00",
            },
        ],
        "report_md": "# Findings\nAlpha beta gamma.\n\n## Details\nSecond section cites source.",
        "research_brief": {
            "scope": "market",
            "output_language": "fr",
            "key_dimensions": ["competition", "funding"],
            "preferred_sources": ["news"],
        },
        "updated_at": "2026-01-01T00:10:00+00:00",
    }

    summary = _build_project_summary(project)

    assert summary["score"] == 0.82
    assert summary["iteration_count"] == 2
    assert summary["best_iteration_score"] == 0.82
    assert summary["last_iteration"]["num"] == 2
    assert summary["sources"]["total_results"] == 4
    assert summary["sources"]["unique_urls"] == 3
    assert summary["sources"]["top_domains"][0] == ("example.com", 1)
    assert summary["assets"]["count"] == 2
    assert summary["assets"]["total_bytes"] == 3072
    assert summary["actions"]["count"] == 3
    assert ("web_search", 2) in summary["actions"]["types"]
    assert summary["report"]["available"] is True
    assert summary["report"]["section_count"] == 2
    assert summary["report"]["word_count"] == 9
    assert summary["brief"]["language"] == "fr"
