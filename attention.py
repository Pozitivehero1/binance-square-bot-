""Attention score for Binance Square."""
POPULAR={"BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT"}
def calculate_attention_score(mtf,btc=None):
    ind=getattr(mtf,"tf_15m",None)
    if ind is None:return 0.0
    score=min(abs(float(getattr(ind,"volume_relative",0) or 0))*15,30)+min(abs(float(getattr(ind,"change_1h",0) or 0))*5,25)+min(abs(float(getattr(ind,"atr_percent",0) or 0))*3,15)
    if getattr(mtf,"symbol","") in POPULAR: score+=15
    return round(min(score,100),2)
