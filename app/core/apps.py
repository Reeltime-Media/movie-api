"""Which app a title, plan or subscription belongs to.

Reeltime and TV5 Entertainment share accounts and the media pipeline but not
catalogs or subscriptions: a title is listed, sold and unlocked only in its app.
"""

from typing import Literal

AppName = Literal["reeltime", "tv5"]

REELTIME: AppName = "reeltime"
TV5: AppName = "tv5"
APP_NAMES: tuple[AppName, ...] = (REELTIME, TV5)
