
import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX
from sklearn.linear_model import RidgeCV
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

try:
    from ..prediction.forecast_enhanced import predict_stock_price_enhanced
    USE_ENHANCED = True
except ImportError:
    USE_ENHANCED = False
    print("Enhanced forecast not available, using basic methods")


def sarimax_forecast(df: pd.DataFrame, ahead_days: int = 5):
    series = df.sort_values("trade_date")["close"].astype(float)
    if len(series) < 60:
        return None
    model = SARIMAX(
        series,
        order=(1, 1, 1),
        seasonal_order=(0, 0, 0, 0),
        enforce_stationarity=False,
        enforce_invertibility=False,
    )
    res = model.fit(disp=False)
    pred = res.get_forecast(steps=ahead_days)
    yhat = pred.predicted_mean.values
    conf = pred.conf_int(alpha=0.2).values
    return yhat, conf[:, 0], conf[:, 1]


def feature_regression_forecast(df: pd.DataFrame, ahead_days: int = 5):
    """基于收益率特征的 Ridge 回归预测（基础降级方案）"""
    df = df.sort_values("trade_date").copy()
    close = df["close"].astype(float)
    df["ret1"] = close.pct_change()
    df["ma5"] = close.rolling(5).mean()
    df["ma10"] = close.rolling(10).mean()
    df["ema12"] = close.ewm(span=12, adjust=False).mean()
    df["ema26"] = close.ewm(span=26, adjust=False).mean()
    df["vol_z"] = (
        (df["vol"] - df["vol"].rolling(20).mean()) /
        (df["vol"].rolling(20).std() + 1e-9)
    )
    # 使用比率特征而非原始价格
    df["ma5_bias"] = (close - df["ma5"]) / (df["ma5"] + 1e-9)
    df["ma10_bias"] = (close - df["ma10"]) / (df["ma10"] + 1e-9)
    df["ema12_bias"] = (close - df["ema12"]) / (df["ema12"] + 1e-9)
    df["ema26_bias"] = (close - df["ema26"]) / (df["ema26"] + 1e-9)
    df = df.dropna().copy()

    feature_cols = ["ret1", "ma5_bias", "ma10_bias", "ema12_bias", "ema26_bias", "vol_z"]
    X = df[feature_cols].values
    y = df["close"].values
    if len(y) < 80:
        return None

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("ridge", RidgeCV(alphas=np.logspace(-3, 3, 20))),
    ])
    pipe.fit(X[:-ahead_days], y[:-ahead_days])
    sigma = np.std(y[:-ahead_days] - pipe.predict(X[:-ahead_days]))

    last_close = float(y[-1])
    daily_rets = np.diff(np.log(y))
    recent_rets = daily_rets[-20:] if len(daily_rets) >= 20 else daily_rets
    avg_ret = float(np.mean(recent_rets)) * 0.5  # 向零收缩

    preds, lo, hi = [], [], []
    for day in range(ahead_days):
        step = day + 1
        pred_y = last_close * np.exp(avg_ret * step)
        bound = 1.28 * sigma * np.sqrt(step)
        preds.append(pred_y)
        lo.append(pred_y - bound)
        hi.append(pred_y + bound)

    return np.array(preds), np.array(lo), np.array(hi)


def predict_stock_price(df: pd.DataFrame, symbol: str, ahead_days: int = 5):
    """预测股票价格 — 优先使用增强版集成模型"""
    if USE_ENHANCED:
        try:
            result = predict_stock_price_enhanced(df, symbol, ahead_days)
            if result.get("method") != "none":
                return result
        except Exception as e:
            print(f"Enhanced prediction failed for {symbol}: {e}")

    return predict_stock_price_basic(df, symbol, ahead_days)


def predict_stock_price_basic(df: pd.DataFrame, symbol: str, ahead_days: int = 5):
    """基础版预测（降级方案）"""
    try:
        if df.empty or len(df) < 30:
            return {
                "symbol": symbol,
                "error": "Insufficient data for prediction",
                "predictions": [],
                "method": "none"
            }

        try:
            result = feature_regression_forecast(df, ahead_days)
            if result is not None:
                yhat, yhat_lower, yhat_upper = result
                predictions = []
                for i in range(ahead_days):
                    predictions.append({
                        "day": i + 1,
                        "predicted_price": float(yhat[i]),
                        "lower_bound": float(yhat_lower[i]),
                        "upper_bound": float(yhat_upper[i])
                    })
                return {
                    "symbol": symbol,
                    "predictions": predictions,
                    "method": "feature_regression",
                    "confidence": 0.5
                }
        except Exception as e:
            print(f"Feature regression failed for {symbol}: {e}")

        try:
            result = sarimax_forecast(df, ahead_days)
            if result is not None:
                yhat, yhat_lower, yhat_upper = result
                predictions = []
                for i in range(ahead_days):
                    predictions.append({
                        "day": i + 1,
                        "predicted_price": float(yhat[i]),
                        "lower_bound": float(yhat_lower[i]),
                        "upper_bound": float(yhat_upper[i])
                    })
                return {
                    "symbol": symbol,
                    "predictions": predictions,
                    "method": "sarimax",
                    "confidence": 0.45
                }
        except Exception as e:
            print(f"SARIMAX failed for {symbol}: {e}")

        close_prices = df.sort_values("trade_date")["close"].astype(float)
        if len(close_prices) >= 10:
            last_price = float(close_prices.iloc[-1])
            daily_rets = close_prices.pct_change().dropna().values
            recent_rets = daily_rets[-20:] if len(daily_rets) >= 20 else daily_rets
            avg_ret = float(np.mean(recent_rets)) * 0.5
            vol = float(np.std(daily_rets[-60:])) if len(daily_rets) >= 60 else float(np.std(daily_rets))

            predictions = []
            for i in range(ahead_days):
                step = i + 1
                predicted_price = last_price * (1 + avg_ret * step)
                bound_width = 1.28 * vol * last_price * np.sqrt(step)
                predictions.append({
                    "day": step,
                    "predicted_price": float(predicted_price),
                    "lower_bound": float(predicted_price - bound_width),
                    "upper_bound": float(predicted_price + bound_width)
                })

            return {
                "symbol": symbol,
                "predictions": predictions,
                "method": "linear_trend",
                "confidence": 0.3
            }

        return {
            "symbol": symbol,
            "error": "All prediction methods failed",
            "predictions": [],
            "method": "none"
        }

    except Exception as e:
        return {
            "symbol": symbol,
            "error": f"Prediction error: {str(e)}",
            "predictions": [],
            "method": "none"
        }
