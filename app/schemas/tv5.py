from app.schemas.content import ContentListItemRead
from app.schemas.match import MatchDetailsRead


class Tv5MatchListItemRead(ContentListItemRead):
    match: MatchDetailsRead
