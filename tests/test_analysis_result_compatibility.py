import matplotlib.pyplot as plt
import pandas as pd

from core.analysis_result import ResultCollector


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
