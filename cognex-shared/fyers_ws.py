"""Live LTP over the Fyers data WebSocket (does not use REST quota)."""
import threading, time


class LivePrices:
    def __init__(self, client_id, token_getter, log=print):
        self.cid = client_id
        self.tg = token_getter
        self.log = log
        self.prices = {}
        self.want = set()
        self.sub = set()
        self.sock = None
        self.tok = None
        self.connected = False
        self.lock = threading.Lock()

    def _make(self, tok):
        from fyers_apiv3.FyersWebsocket import data_ws

        def on_msg(m):
            try:
                if isinstance(m, dict) and m.get("symbol") and m.get("ltp") is not None:
                    self.prices[m["symbol"]] = (float(m["ltp"]), time.time())
            except Exception:
                pass

        def on_open():
            self.connected = True
            self.sub = set()
            self._push()

        def on_close(m):
            self.connected = False

        def on_err(m):
            self.log(f"WS error: {str(m)[:120]}")

        return data_ws.FyersDataSocket(
            access_token=f"{self.cid}:{tok}", log_path="", litemode=True,
            write_to_file=False, reconnect=True, on_connect=on_open,
            on_close=on_close, on_error=on_err, on_message=on_msg)

    def _push(self):
        with self.lock:
            add = list(self.want - self.sub)
            rem = list(self.sub - self.want)
            try:
                if add:
                    self.sock.subscribe(symbols=add, data_type="SymbolUpdate")
                    self.sub |= set(add)
                if rem:
                    self.sock.unsubscribe(symbols=rem, data_type="SymbolUpdate")
                    self.sub -= set(rem)
            except Exception as e:
                self.log(f"WS subscribe error: {e}")

    def sync(self, symbols):
        """Call every cycle with the symbols we need prices for."""
        tok = self.tg()
        if self.sock is None or tok != self.tok:
            try:
                if self.sock is not None:
                    self.sock.close_connection()
            except Exception:
                pass
            self.tok = tok
            self.connected = False
            self.sub = set()
            self.sock = self._make(tok)
            threading.Thread(target=self.sock.connect, daemon=True).start()
        self.want = set(symbols)
        if self.connected:
            self._push()

    def get(self, symbol, max_age=90):
        """Last streamed LTP, or None if the socket is down or the price is too old."""
        if not self.connected:
            return None
        p = self.prices.get(symbol)
        if p and time.time() - p[1] <= max_age:
            return p[0]
        return None
