"""Robin-compatible configurable search federation (upstream main, b5d4f5f)."""
from __future__ import annotations

DEFAULT_SEARCH_ENGINES = (
    ("Ahmia", "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/search/?q={query}"),
    ("OnionLand", "http://3bbad7fauom4d6sgppalyqddsqbf5u5p56b5k5uk2zxsy3d6ey2jobad.onion/search?q={query}"),
    ("Torgle", "http://iy3544gmoeclh5de6gez2256v6pjh4omhpqdh2wpeeppjtvqmjhkfwad.onion/torgle/?query={query}"),
    ("Amnesia", "http://amnesia7u5odx5xbwtpnqk3edybgud5bmiagu75bnqx2crntw5kry7ad.onion/search?query={query}"),
    ("Kaizer", "http://kaizerwfvp5gxu6cppibp7jhcqptavq3iqef66wbxenh6a2fklibdvid.onion/search?q={query}"),
    ("Anima", "http://anima4ffe27xmakwnseih3ic2y7y3l6e7fucwk4oerdn4odf7k74tbid.onion/search?q={query}"),
    ("Tornado", "http://tornadoxn3viscgz647shlysdy7ea5zqzwda7hierekeuokh5eh5b3qd.onion/search?q={query}"),
    ("TorNet", "http://tornetupfu7gcgidt33ftnungxzyfq2pygui5qdoyss34xbgx2qruzid.onion/search?q={query}"),
    ("Torland", "http://torlbmqwtudkorme6prgfpmsnile7ug2zm4u3ejpcncxuhpu4k2j4kyd.onion/index.php?a=search&q={query}"),
    ("Find Tor", "http://findtorroveq5wdnipkaojfpqulxnkhblymc7aramjzajcvpptd4rjqd.onion/search?q={query}"),
    ("Excavator", "http://2fd6cemt4gmccflhm6imvdfvli3nf7zn6rfrwpsy7uhxrgbypvwf5fad.onion/search?query={query}"),
    ("Onionway", "http://oniwayzz74cv2puhsgx4dpjwieww4wdphsydqvf5q7eyz4myjvyw26ad.onion/search.php?s={query}"),
    ("Tor66", "http://tor66sewebgixwhcqfnp5inzp5x5uohhdy3kvtnyfxc2e5mxiuh34iid.onion/search?q={query}"),
    ("OSS", "http://3fzh7yuupdfyjhwt3ugzqqof6ulbcl27ecev33knxe3u7goi3vfn2qqd.onion/oss/index.php?search={query}"),
    ("Torgol", "http://torgolnpeouim56dykfob6jh5r2ps2j73enc42s2um4ufob3ny4fcdyd.onion/?q={query}"),
    ("The Deep Searches", "http://searchgf7gdtauh7bhnbyed4ivxqmuoat3nm6zfrg3ymkq6mtnpye3ad.onion/search?q={query}"),
)

DEFAULT_PRESETS = {
    "threat_intel": ("General cybercrime intelligence: artifacts, actors, and next steps.",
        "Ground every IOC and claim in supplied sources. Include cited sources, artifacts, evidence-based insights, and corroboration steps."),
    "ransomware_malware": ("Ransomware groups, malware families, C2 infrastructure, and TTPs.",
        "Focus on malware, ransomware, infrastructure, observed TTPs and victims. Map to ATT&CK only where evidence supports it."),
    "personal_identity": ("Exposed personal data, breach sources, and individual exposure risk.",
        "Minimize personal data in the report. Do not repeat sensitive identifiers unless essential to the authorized question; recommend protective steps."),
    "corporate_espionage": ("Leaked corporate data, insider activity, and business impact.",
        "Focus on organization, sector, leak claims, source reliability and business exposure; distinguish allegation from verified fact."),
}
