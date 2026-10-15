import asyncio
from collections import defaultdict


_user_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def get_user_lock(user_id: int) -> asyncio.Lock:
    return _user_locks[user_id]
