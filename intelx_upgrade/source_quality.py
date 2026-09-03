from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlsplit
import math, re

@dataclass(frozen=True, slots=True)
class SourceScore:
    authority: float
    relevance: float
    freshness: float
    independence: float
    accessibility: float
    total: float

PRIMARY_HINTS=("gov","edu","who.int","un.org","sec.gov","europa.eu")
LOW_QUALITY_HINTS=("pinterest","quora","forums","aggregator","unknown")

class SourceQuality:
    def score(self,url:str,title:str,snippet:str,query_terms:set[str],published_age_days:float|None,
              duplicate_count:int=0)->SourceScore:
        host=(urlsplit(url).hostname or "").lower()
        authority=0.55
        if any(x in host for x in PRIMARY_HINTS): authority+=0.30
        if any(x in host for x in LOW_QUALITY_HINTS): authority-=0.20
        text=(title+" "+snippet).lower()
        matched=sum(1 for t in query_terms if t.lower() in text)
        relevance=min(1.0, matched/max(1,len(query_terms)))
        freshness=1.0 if published_age_days is None else math.exp(-max(0,published_age_days)/3650)
        independence=1.0/(1.0+duplicate_count*0.5)
        accessibility=0.95 if url.startswith(("https://","http://")) else 0.6
        total=round(max(0,min(1,0.35*authority+0.30*relevance+0.15*freshness+0.15*independence+0.05*accessibility)),4)
        return SourceScore(authority,relevance,freshness,independence,accessibility,total)

    def rank(self,sources,list_query_terms):
        return sorted(sources,key=lambda s:self.score(s.url,s.title,s.snippet,set(list_query_terms),None).total,reverse=True)

    def normalize_title(self,title:str)->str:
        return re.sub(r"\s+"," ",title).strip().lower()

    def quality_bucket(self,score:float)->str:
        if score>=0.8:return "high"
        if score>=0.6:return "medium"
        return "low"
