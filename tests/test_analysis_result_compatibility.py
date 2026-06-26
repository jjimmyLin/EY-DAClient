import matplotlib.pyplot as plt
import pandas as pd

from core.analysis_result import AnalysisResult, ResultCollector


def test_add_table_accepts_dataframe_keyword():
    collector = ResultCollector()

    collector.add_table(
        title="Products",
        dataframe=pd.DataFrame({"product": ["Apple"], "price": [1]}),
    )

    table = collector._result.tables[0]
    assert table.columns == ["product", "price"]
    assert table.rows == [["Apple", 1]]


def test_add_chart_accepts_matplotlib_figure_keyword():
    collector = ResultCollector()
    figure, axis = plt.subplots()
    axis.plot([1, 2], [3, 4])

    try:
        collector.add_chart(
            title="Trend",
            matplotlib_figure=figure,
            caption="Example",
        )
    finally:
        plt.close(figure)

    chart = collector._result.charts[0]
    assert chart.title == "Trend"
    assert chart.caption == "Example"
    assert chart.image_base64


def test_add_answer_records_question_oriented_result():
    collector = ResultCollector()

    collector.add_answer(
        "Q1",
        "Calculate total revenue",
        "Total revenue is 115 CNY.",
        supporting_metrics=["Total revenue"],
        supporting_tables=["Revenue by product"],
        confidence_or_notes="Computed from non-null price and quantity rows.",
    )

    answer = collector._result.answers[0]
    assert answer.answer_id == "Q1"
    assert answer.question == "Calculate total revenue"
    assert answer.answer == "Total revenue is 115 CNY."
    assert answer.supporting_metrics == ["Total revenue"]
    assert answer.supporting_tables == ["Revenue by product"]
    assert "non-null" in answer.confidence_or_notes


def test_analysis_result_from_dict_accepts_answers():
    result = AnalysisResult.from_dict(
        {
            "answers": [
                {
                    "id": "1",
                    "question": "How many rows?",
                    "answer": "10 rows.",
                    "supporting_metrics": ["Rows"],
                    "notes": "Counted from the active sheet.",
                }
            ]
        }
    )

    assert result.answers[0].answer_id == "1"
    assert result.answers[0].question == "How many rows?"
    assert result.answers[0].supporting_metrics == ["Rows"]
    assert result.answers[0].confidence_or_notes == "Counted from the active sheet."
