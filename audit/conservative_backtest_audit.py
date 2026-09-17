"""Conservative implementation audit for the submitted allocation notebook.

Run this script from the repository root after executing the original notebook.
It deliberately does not modify the submitted notebook or its outputs.
"""

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "Outputs" / "Union_Investment"
RESULTS = ROOT / "results" / "tables"


def calculate_metrics(
    returns: pd.Series, risk_free: pd.Series | None = None
) -> dict[str, float]:
    """Calculate annualised monthly-return metrics and maximum drawdown."""
    clean_returns = returns.dropna()
    wealth = (1.0 + clean_returns).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    annual_return = clean_returns.mean() * 12.0
    annual_volatility = clean_returns.std(ddof=1) * np.sqrt(12.0)

    excess_sharpe = np.nan
    if risk_free is not None:
        excess = clean_returns - risk_free.reindex(clean_returns.index)
        excess_sharpe = (
            excess.mean() * 12.0 / (excess.std(ddof=1) * np.sqrt(12.0))
        )

    return {
        "months": float(len(clean_returns)),
        "annualized_return": annual_return,
        "annualized_volatility": annual_volatility,
        "return_to_volatility": annual_return / annual_volatility,
        "sharpe_excess_over_short_treasury": excess_sharpe,
        "maximum_drawdown": drawdown.min(),
    }


def main() -> None:
    asset_file = ROOT / "Asset Data.xlsx"
    weights_file = OUTPUTS / "rule_based_allocations_final.csv"
    returns_file = OUTPUTS / "strategy_returns_primary.csv"

    missing = [path for path in (asset_file, weights_file, returns_file) if not path.exists()]
    if missing:
        missing_list = "\n".join(f"- {path.relative_to(ROOT)}" for path in missing)
        raise FileNotFoundError(
            "Required files are missing. Run the original notebook with authorised "
            f"input data first:\n{missing_list}"
        )

    assets = pd.read_excel(asset_file)
    assets["Date"] = pd.to_datetime(assets["Date"], format="%m/%Y", errors="coerce")
    assets = assets.dropna(subset=["Date"])
    assets["Date"] = assets["Date"].dt.to_period("M").dt.to_timestamp()
    assets = assets.set_index("Date").sort_index().select_dtypes(include=[np.number])

    weights = pd.read_csv(weights_file, index_col=0, parse_dates=True).sort_index()
    weights = weights.reindex(columns=assets.columns).fillna(0.0)
    submitted_returns = pd.read_csv(
        returns_file, index_col=0, parse_dates=True
    ).sort_index()

    # The submitted implementation uses weights dated t with returns dated t.
    # Delay weights by one month to create a feasible monthly implementation.
    lagged_weights = weights.shift(1)
    lagged_returns = (assets.reindex(lagged_weights.index) * lagged_weights).sum(axis=1)

    # February 2005 is the first month after complete coverage begins for all
    # assets, allowing for the one-month implementation delay.
    comparison = pd.concat(
        {
            "published_rule": submitted_returns["Rule-Based"],
            "lagged_rule": lagged_returns,
            "saa_benchmark": submitted_returns["SAA Benchmark"],
        },
        axis=1,
    ).loc["2005-02-01":"2024-12-01"].dropna()

    # Illustrative 10 bps one-way cost applied to monthly portfolio turnover.
    turnover = 0.5 * lagged_weights.diff().abs().sum(axis=1)
    comparison["lagged_rule_after_10bp_cost"] = (
        comparison["lagged_rule"]
        - 0.001 * turnover.reindex(comparison.index).fillna(0.0)
    )

    risk_free = assets["Short-term treasury index"].reindex(comparison.index)
    summary = pd.DataFrame(
        {
            name: calculate_metrics(comparison[name], risk_free=risk_free)
            for name in comparison
        }
    ).T
    summary["annualized_turnover"] = np.nan
    annual_turnover = turnover.reindex(comparison.index).mean() * 12.0
    summary.loc["lagged_rule", "annualized_turnover"] = annual_turnover
    summary.loc[
        "lagged_rule_after_10bp_cost", "annualized_turnover"
    ] = annual_turnover

    RESULTS.mkdir(parents=True, exist_ok=True)
    output_file = RESULTS / "conservative_audit.csv"
    summary.to_csv(output_file)
    print(summary.to_string(float_format=lambda value: f"{value:.6f}"))
    print(f"\nSaved: {output_file.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

