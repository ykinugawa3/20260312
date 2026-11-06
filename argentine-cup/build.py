"""data.json と template.html から、ページを組み立てる。
  index.html   : そのままブラウザで開ける完成版
  artifact.html: 公開用（<html>などの外枠なし）
"""
import json, pathlib
here = pathlib.Path(__file__).parent
keep = ['year','kai','date','horse','sexage','waku','umaban','pop','odds','jockey','trainer','sire','damsire',
        'prev_race','prev_grade','prev_cat','prev_venue','prev_dist','prev_fin','time','heads','weather']
data = sorted(json.loads((here/'data.json').read_text(encoding='utf-8')), key=lambda r: -r['year'])
data = [{k: r[k] for k in keep} for r in data]
body = (here/'template.html').read_text(encoding='utf-8').replace(
    '__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':')))
(here/'artifact.html').write_text(body, encoding='utf-8')
head = '<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
title_end = body.index('</style>') + len('</style>')
(here/'index.html').write_text(head + body[:title_end] + '\n</head>\n<body>\n' + body[title_end:] + '\n</body>\n</html>\n', encoding='utf-8')
print('built', len(data), 'rows')
