import asyncio
from intelx_upgrade.scheduler import bounded_call
def test_cancel_safe():
    async def main():
        async def f(): raise asyncio.CancelledError
        try: await bounded_call(f)
        except asyncio.CancelledError: return
        raise AssertionError
    asyncio.run(main())
