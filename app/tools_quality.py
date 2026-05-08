"""
Clawzd — Quality validation using DeepEval metrics.
"""
from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/validate")
async def validate_answer(request: Request):
    """Validate an LLM response using DeepEval metrics."""
    data = await request.json()
    input_text = data.get("input", "")
    output_text = data.get("output", "")
    context = data.get("context", [])

    try:
        from deepeval.metrics import AnswerRelevancyMetric, HallucinationMetric
        from deepeval.test_case import LLMTestCase

        test_case = LLMTestCase(
            input=input_text,
            actual_output=output_text,
            context=context,
            expected_output="",
        )
        relevancy = AnswerRelevancyMetric(threshold=0.5)
        hallucination = HallucinationMetric(threshold=0.5)
        relevancy.measure(test_case)
        hallucination.measure(test_case)
        return {
            "relevancy_score": relevancy.score,
            "hallucination_score": hallucination.score,
        }
    except ImportError:
        return {"error": "deepeval not installed"}
    except Exception as e:
        return {"error": str(e)}