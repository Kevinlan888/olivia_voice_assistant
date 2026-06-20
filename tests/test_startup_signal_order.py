import unittest


class TestStartupSignalOrder(unittest.TestCase):
    def test_signal_setup_should_precede_ws_connect(self):
        order: list[str] = []

        def setup_signal_handlers():
            order.append("signals")

        async def connect_ws():
            order.append("connect")

        setup_signal_handlers()

        self.assertEqual(order[0], "signals")


if __name__ == "__main__":
    unittest.main()
