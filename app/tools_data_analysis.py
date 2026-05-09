"""
Clawzd — Automated Data Analysis Engine.

Inspired by Abacus.ai's "AI Data Analyst" and "Revenue Analytics Pro".
Provides automated CSV/Excel analysis with:
- Statistical profiling (distributions, correlations, missing values)
- Pattern detection (trends, anomalies, clusters)
- Auto-generated Chart.js visualizations via __CHART__ markers
- Structured markdown reports with __TABLE__ markers

Usage:
    from app.tools_data_analysis import analyze_file
    result = await analyze_file("data/sales.csv")
"""
import os
import json
import logging
import asyncio
from typing import Optional

logger = logging.getLogger("clawzd.data_analysis")


# ---------------------------------------------------------------------------
# Core analysis engine
# ---------------------------------------------------------------------------

class DataAnalyzer:
    """Automated data analysis engine for CSV/Excel files."""

    def __init__(self, max_rows: int = 50_000, max_charts: int = 5):
        self.max_rows = max_rows
        self.max_charts = max_charts

    def load_file(self, file_path: str):
        """Load a CSV or Excel file into a pandas DataFrame."""
        import pandas as pd

        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(file_path, nrows=self.max_rows)
        elif ext == ".csv":
            # Try common encodings
            for enc in ("utf-8", "latin-1", "cp1252"):
                try:
                    df = pd.read_csv(
                        file_path, nrows=self.max_rows, encoding=enc,
                    )
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            else:
                raise ValueError(f"Cannot decode file: {file_path}")
        elif ext == ".tsv":
            df = pd.read_csv(
                file_path, sep="\t", nrows=self.max_rows, encoding="utf-8",
            )
        else:
            raise ValueError(
                f"Unsupported file type: {ext}. "
                "Supported: .csv, .tsv, .xlsx, .xls"
            )

        return df

    def profile_data(self, df) -> dict:
        """Generate a statistical profile of the dataframe."""
        import pandas as pd
        import numpy as np

        profile = {
            "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
            "columns": [],
            "missing_total": int(df.isnull().sum().sum()),
            "duplicate_rows": int(df.duplicated().sum()),
            "memory_mb": round(df.memory_usage(deep=True).sum() / 1e6, 2),
        }

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        categorical_cols = df.select_dtypes(
            include=["object", "category"]
        ).columns.tolist()
        datetime_cols = df.select_dtypes(include=["datetime"]).columns.tolist()

        profile["numeric_columns"] = numeric_cols
        profile["categorical_columns"] = categorical_cols
        profile["datetime_columns"] = datetime_cols

        for col in df.columns:
            col_info = {
                "name": col,
                "dtype": str(df[col].dtype),
                "missing": int(df[col].isnull().sum()),
                "missing_pct": round(
                    df[col].isnull().sum() / len(df) * 100, 1
                ),
                "unique": int(df[col].nunique()),
            }

            if col in numeric_cols:
                desc = df[col].describe()
                col_info.update({
                    "mean": round(float(desc.get("mean", 0)), 4),
                    "std": round(float(desc.get("std", 0)), 4),
                    "min": float(desc.get("min", 0)),
                    "max": float(desc.get("max", 0)),
                    "median": round(float(df[col].median()), 4),
                    "q25": float(desc.get("25%", 0)),
                    "q75": float(desc.get("75%", 0)),
                })
            elif col in categorical_cols:
                top_values = (
                    df[col].value_counts().head(5).to_dict()
                )
                col_info["top_values"] = {
                    str(k): int(v) for k, v in top_values.items()
                }

            profile["columns"].append(col_info)

        # Correlation matrix for numeric columns
        if len(numeric_cols) >= 2:
            corr = df[numeric_cols].corr()
            # Find strong correlations (|r| > 0.7)
            strong_corrs = []
            for i in range(len(numeric_cols)):
                for j in range(i + 1, len(numeric_cols)):
                    r = float(corr.iloc[i, j])
                    if abs(r) > 0.7:
                        strong_corrs.append({
                            "col1": numeric_cols[i],
                            "col2": numeric_cols[j],
                            "correlation": round(r, 3),
                        })
            profile["strong_correlations"] = strong_corrs

        return profile

    def detect_patterns(self, df, profile: dict) -> list:
        """Detect trends, anomalies, and patterns."""
        import pandas as pd
        import numpy as np

        patterns = []

        # 1. Time series detection
        for col_info in profile["columns"]:
            col = col_info["name"]
            if col_info["dtype"].startswith("datetime"):
                patterns.append({
                    "type": "time_series",
                    "column": col,
                    "description": f"Column '{col}' is a datetime — "
                                   "potential time series analysis candidate.",
                })

            # Check string columns that might be dates
            if (
                col_info["dtype"] == "object"
                and col_info["unique"] > 5
                and any(
                    kw in col.lower()
                    for kw in ("date", "time", "day", "month", "year", "ts")
                )
            ):
                try:
                    pd.to_datetime(df[col].dropna().head(10))
                    patterns.append({
                        "type": "implicit_date",
                        "column": col,
                        "description": f"Column '{col}' appears to contain "
                                       "dates stored as strings.",
                    })
                except Exception:
                    pass

        # 2. Outlier detection (IQR method)
        for col in profile.get("numeric_columns", []):
            q1 = df[col].quantile(0.25)
            q3 = df[col].quantile(0.75)
            iqr = q3 - q1
            if iqr > 0:
                outliers = df[
                    (df[col] < q1 - 1.5 * iqr) | (df[col] > q3 + 1.5 * iqr)
                ]
                if len(outliers) > 0:
                    pct = round(len(outliers) / len(df) * 100, 1)
                    patterns.append({
                        "type": "outliers",
                        "column": col,
                        "count": len(outliers),
                        "percentage": pct,
                        "description": (
                            f"Column '{col}' has {len(outliers)} outliers "
                            f"({pct}%) detected via IQR method."
                        ),
                    })

        # 3. High cardinality warnings
        for col_info in profile["columns"]:
            if (
                col_info["dtype"] == "object"
                and col_info["unique"] > 100
                and col_info["unique"] / profile["shape"]["rows"] > 0.5
            ):
                patterns.append({
                    "type": "high_cardinality",
                    "column": col_info["name"],
                    "unique": col_info["unique"],
                    "description": (
                        f"Column '{col_info['name']}' has very high "
                        f"cardinality ({col_info['unique']} unique values) — "
                        "may be an identifier column."
                    ),
                })

        # 4. Missing data patterns
        missing_cols = [
            ci for ci in profile["columns"] if ci["missing_pct"] > 10
        ]
        if missing_cols:
            patterns.append({
                "type": "missing_data",
                "columns": [ci["name"] for ci in missing_cols],
                "description": (
                    f"{len(missing_cols)} column(s) have >10% missing data: "
                    + ", ".join(
                        f"{ci['name']} ({ci['missing_pct']}%)"
                        for ci in missing_cols[:5]
                    )
                ),
            })

        # 5. Strong correlations
        for corr in profile.get("strong_correlations", []):
            direction = "positive" if corr["correlation"] > 0 else "negative"
            patterns.append({
                "type": "correlation",
                "columns": [corr["col1"], corr["col2"]],
                "value": corr["correlation"],
                "description": (
                    f"Strong {direction} correlation (r={corr['correlation']}) "
                    f"between '{corr['col1']}' and '{corr['col2']}'."
                ),
            })

        return patterns

    def generate_visualizations(
        self, df, profile: dict, focus: str = "",
    ) -> list:
        """Generate Chart.js-compatible chart configs.

        Returns list of __CHART__ marker strings ready for injection.
        """
        import pandas as pd
        import numpy as np

        charts = []
        numeric_cols = profile.get("numeric_columns", [])
        categorical_cols = profile.get("categorical_columns", [])

        # 1. Distribution of numeric columns (histogram-style bar chart)
        for col in numeric_cols[:2]:
            try:
                hist, edges = np.histogram(df[col].dropna(), bins=10)
                labels = [
                    f"{edges[i]:.1f}-{edges[i+1]:.1f}"
                    for i in range(len(edges) - 1)
                ]
                charts.append({
                    "type": "bar",
                    "title": f"Distribution of {col}",
                    "labels": labels,
                    "datasets": [{
                        "label": col,
                        "data": [int(h) for h in hist],
                    }],
                })
            except Exception:
                pass

        # 2. Top categories (bar chart)
        for col in categorical_cols[:2]:
            try:
                top = df[col].value_counts().head(8)
                charts.append({
                    "type": "bar",
                    "title": f"Top values in {col}",
                    "labels": [str(l) for l in top.index.tolist()],
                    "datasets": [{
                        "label": "Count",
                        "data": top.values.tolist(),
                    }],
                })
            except Exception:
                pass

        # 3. Pie chart for first categorical column with low cardinality
        for col in categorical_cols:
            if df[col].nunique() <= 8:
                vc = df[col].value_counts()
                charts.append({
                    "type": "pie",
                    "title": f"Distribution of {col}",
                    "labels": [str(l) for l in vc.index.tolist()],
                    "datasets": [{
                        "label": col,
                        "data": vc.values.tolist(),
                    }],
                })
                break

        # 4. Correlation scatter (if strong correlations found)
        for corr in profile.get("strong_correlations", [])[:1]:
            col1, col2 = corr["col1"], corr["col2"]
            try:
                sample = df[[col1, col2]].dropna().head(100)
                charts.append({
                    "type": "scatter",
                    "title": f"Correlation: {col1} vs {col2} "
                             f"(r={corr['correlation']})",
                    "datasets": [{
                        "label": f"{col1} vs {col2}",
                        "data": [
                            {"x": float(row[col1]), "y": float(row[col2])}
                            for _, row in sample.iterrows()
                        ],
                    }],
                })
            except Exception:
                pass

        # 5. Time series line chart (if datetime column detected)
        datetime_cols = profile.get("datetime_columns", [])
        if datetime_cols and numeric_cols:
            dt_col = datetime_cols[0]
            val_col = numeric_cols[0]
            try:
                ts = df[[dt_col, val_col]].dropna().sort_values(dt_col)
                # Sample if too many points
                if len(ts) > 50:
                    step = max(1, len(ts) // 50)
                    ts = ts.iloc[::step]
                charts.append({
                    "type": "line",
                    "title": f"{val_col} over time",
                    "labels": [
                        str(d)[:10] for d in ts[dt_col].tolist()
                    ],
                    "datasets": [{
                        "label": val_col,
                        "data": [
                            float(v) if pd.notna(v) else 0
                            for v in ts[val_col].tolist()
                        ],
                    }],
                })
            except Exception:
                pass

        return charts[: self.max_charts]

    def generate_report(
        self,
        file_path: str,
        df,
        profile: dict,
        patterns: list,
        charts: list,
    ) -> str:
        """Generate a structured markdown report with insights."""

        fname = os.path.basename(file_path)
        report = []

        # Header
        report.append(f"# 📊 Data Analysis Report: `{fname}`\n")

        # Overview table
        overview_table = {
            "title": "Dataset Overview",
            "headers": ["Metric", "Value"],
            "rows": [
                ["Rows", str(profile["shape"]["rows"])],
                ["Columns", str(profile["shape"]["columns"])],
                ["Numeric columns", str(len(profile.get("numeric_columns", [])))],
                [
                    "Categorical columns",
                    str(len(profile.get("categorical_columns", []))),
                ],
                ["Missing values", str(profile["missing_total"])],
                ["Duplicate rows", str(profile["duplicate_rows"])],
                ["Memory", f"{profile['memory_mb']} MB"],
            ],
        }
        report.append(
            f'__TABLE__{json.dumps(overview_table, ensure_ascii=False)}__TABLE__'
        )
        report.append("")

        # Column details table
        col_headers = [
            "Column", "Type", "Missing %", "Unique", "Mean/Top",
        ]
        col_rows = []
        for ci in profile["columns"][:20]:
            mean_or_top = ""
            if "mean" in ci:
                mean_or_top = f"{ci['mean']}"
            elif "top_values" in ci:
                top = list(ci["top_values"].keys())[:2]
                mean_or_top = ", ".join(top)
            col_rows.append([
                ci["name"],
                ci["dtype"],
                f"{ci['missing_pct']}%",
                str(ci["unique"]),
                mean_or_top,
            ])

        col_table = {
            "title": "Column Details",
            "headers": col_headers,
            "rows": col_rows,
        }
        report.append("## Column Details\n")
        report.append(
            f'__TABLE__{json.dumps(col_table, ensure_ascii=False)}__TABLE__'
        )
        report.append("")

        # Patterns & insights
        if patterns:
            report.append("## 🔍 Key Insights\n")
            for p in patterns:
                emoji = {
                    "outliers": "⚠️",
                    "correlation": "🔗",
                    "missing_data": "❓",
                    "time_series": "📈",
                    "implicit_date": "📅",
                    "high_cardinality": "🏷️",
                }.get(p["type"], "💡")
                report.append(f"- {emoji} **{p['type'].replace('_', ' ').title()}**: {p['description']}")
            report.append("")

        # Charts
        if charts:
            report.append("## 📈 Visualizations\n")
            for chart in charts:
                chart_json = json.dumps(chart, ensure_ascii=False)
                report.append(f"__CHART__{chart_json}__CHART__\n")

        # Recommendations
        report.append("## 💡 Recommendations\n")
        if profile["missing_total"] > 0:
            report.append(
                "- **Missing values**: Consider imputation or "
                "investigate why data is missing."
            )
        if profile["duplicate_rows"] > 0:
            report.append(
                f"- **Duplicates**: {profile['duplicate_rows']} duplicate "
                "rows found — consider deduplication."
            )
        if profile.get("strong_correlations"):
            report.append(
                "- **Correlations**: Strong correlations detected — "
                "watch for multicollinearity in models."
            )
        outlier_patterns = [p for p in patterns if p["type"] == "outliers"]
        if outlier_patterns:
            report.append(
                "- **Outliers**: Investigate flagged outliers — "
                "they may indicate data quality issues or real extremes."
            )
        report.append("")

        return "\n".join(report)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_analyzer = DataAnalyzer()


async def analyze_file(
    file_path: str, focus: str = "", max_charts: int = 5,
) -> dict:
    """Full analysis pipeline: load → profile → detect → visualize → report.

    Args:
        file_path: Path to CSV/Excel file (relative to workspace).
        focus: Optional analysis focus (trends, correlations, anomalies).
        max_charts: Maximum charts to generate.

    Returns:
        Dict with keys: output, report, profile, patterns, charts.
    """
    from config import WORKSPACE_DIR

    # Resolve path relative to workspace
    if not os.path.isabs(file_path):
        full_path = os.path.join(WORKSPACE_DIR, file_path)
    else:
        full_path = file_path

    if not os.path.isfile(full_path):
        return {"error": f"File not found: {file_path}"}

    try:
        analyzer = DataAnalyzer(max_charts=max_charts)

        # Run heavy analysis in thread to avoid blocking
        def _analyze():
            df = analyzer.load_file(full_path)
            profile = analyzer.profile_data(df)
            patterns = analyzer.detect_patterns(df, profile)
            charts = analyzer.generate_visualizations(df, profile, focus)
            report = analyzer.generate_report(
                file_path, df, profile, patterns, charts,
            )
            return df, profile, patterns, charts, report

        df, profile, patterns, charts, report = await asyncio.to_thread(
            _analyze
        )

        logger.info(
            "Data analysis complete for %s: %d rows, %d cols, %d patterns, "
            "%d charts",
            file_path,
            profile["shape"]["rows"],
            profile["shape"]["columns"],
            len(patterns),
            len(charts),
        )

        return {
            "output": report,
            "profile": {
                "shape": profile["shape"],
                "missing_total": profile["missing_total"],
                "duplicate_rows": profile["duplicate_rows"],
                "numeric_columns": len(profile.get("numeric_columns", [])),
                "categorical_columns": len(
                    profile.get("categorical_columns", [])
                ),
            },
            "patterns_count": len(patterns),
            "charts_count": len(charts),
        }

    except Exception as e:
        logger.error("Data analysis failed for %s: %s", file_path, e)
        return {"error": f"Analysis failed: {str(e)}"}
