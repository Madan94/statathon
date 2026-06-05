"""Question inference sub-package — cascade for inferring analytical questions from PDFs."""
from template_engine.inference.question_inferrer import infer_questions, QuestionInferrer

__all__ = ["infer_questions", "QuestionInferrer"]
