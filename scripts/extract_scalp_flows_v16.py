"""Read the official GLD archive without editing it; preserve missing observations."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'reports/can_ho_tro_scalp/20261101_flows_v16'
EXPECTED = '7fd2326e38d85c2e6384d979ba6f1d189f9d8c155a91c422d734fbb5de2b6cd9'
HEADERS = ['Date', 'Closing Price', 'Ounces of Gold per Share', 'NAV/Share at 10:30am NYT',
           'Indicative Price per Share at 4:15pm NYT', 'Mid point of bid/ask spread at 4:15pm NYT',
           'Premium/Discount of GLD Mid Point vs Indicative Value of GLD at 4:15pm NYT',
           'Daily Share Volume', 'Total Ounces of Gold in the Trust', 'Tonnes of Gold',
           'Total Net Asset Value in the Trust']
FIELDS = ['close', 'oz_per_share', 'nav_share', 'indicative_share', 'mid_share',
          'premium_percent', 'volume', 'total_oz', 'tonnes', 'nav_total']


def write(path, value):
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    if path.exists():
        assert path.read_text(encoding='utf-8') == content, 'Immutable extraction changed'
    else:
        path.write_text(content, encoding='utf-8')


def main():
    source = RUN/'GLD_archive.xlsx'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == EXPECTED, 'Official source changed'
    book = openpyxl.load_workbook(source, read_only=True, data_only=True)
    sheet = book['US GLD Historical Archive']
    rows = list(sheet.iter_rows(values_only=True))
    assert list(rows[0]) == HEADERS
    data = []; missing = []; undated = []
    for row_number, row in enumerate(rows[1:], 2):
        if not any(v is not None for v in row):
            continue
        try:
            date = datetime.strptime(str(row[0]), '%d-%b-%Y').replace(tzinfo=timezone.utc)
        except ValueError:
            undated.append(dict(row=row_number, values=list(row))); continue
        record = dict(date=date.strftime('%Y-%m-%d'), date_epoch=int(date.timestamp()), source_row=row_number)
        for field, value in zip(FIELDS, row[1:]):
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                record[field] = float(value)
            else:
                record[field] = None
                missing.append(dict(date=record['date'], field=field, raw=value, source_row=row_number))
        data.append(record)
    assert not undated, 'Undated nonblank source rows require inspection'
    data.sort(key=lambda r:r['date_epoch'])
    assert len({r['date'] for r in data}) == len(data), 'Duplicate source dates'
    window = [r for r in data if '2020-01-01' <= r['date'] < '2026-10-25']
    required = ('close','oz_per_share','premium_percent','volume','total_oz')
    valid = [r for r in window if all(r[k] is not None for k in required) and
             all(r[k] > 0 for k in required if k != 'premium_percent')]
    gaps = [dict(left=a['date'],right=b['date'],days=(b['date_epoch']-a['date_epoch'])//86400)
            for a,b in zip(valid,valid[1:]) if b['date_epoch']-a['date_epoch'] > 4*86400]
    negative = [dict(date=r['date'], field=k, value=r[k]) for r in window
                for k in ('close','oz_per_share','volume','total_oz') if r[k] is not None and r[k] <= 0]
    assert not negative, 'Nonpositive required field requires inspection'
    normalized = dict(fields=FIELDS, headers=HEADERS, rows=data)
    write(RUN/'GLD_normalized.json', normalized)
    manifest = dict(source_url='https://api.spdrgoldshares.com/api/v1/historical-archive?exchange=NYSE&lang=en&product=gld',
        official_page='https://www.spdrgoldshares.com/usa/gld/',source_sha256=digest,
        normalized_sha256=hashlib.sha256((RUN/'GLD_normalized.json').read_bytes()).hexdigest(),
        sheet=sheet.title, rows=len(data), first=data[0]['date'], last=data[-1]['date'],
        extraction='Bundled Python/openpyxl read_only,data_only;no workbook edit. Raw numeric values preserved;missing/text retained as null and logged.',
        units=dict(premium='Source percent;divide100 for fraction.',volume='Daily shares traded.',
                   shares_proxy='total_oz/oz_per_share;not an independently reported historical share count.'),
        missing=missing,undated=undated,required_window=dict(start='2020-01-01',end_exclusive='2026-10-25',
            rows=len(window),common_valid=len(valid),gaps_over_four_days=gaps,nonpositive=negative),
        caveats=['Historical archive is a current vintage subject to changes;no archived publication timestamps or revision history.',
                 'Date labels are source calendar dates,not a verified feed/UTC timestamp.',
                 'A 72-hour lag is a conservative operational assumption,not proof of point-in-time availability.',
                 'Raw archive retained locally for reproducibility;link to official source rather than redistributing it.'])
    write(RUN/'GLD_DATA_MANIFEST.json', manifest)
    book.close()
    print(json.dumps(dict(rows=len(data),missing_fields=len(missing),window=manifest['required_window'],
                          missing_examples=missing[:6]),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
