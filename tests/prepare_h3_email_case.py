"""Render an email case as a validated API request; does not submit or upload."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=['1', '2'])
    parser.add_argument('--image-url', action='append', required=True,
                        help='Repeat exactly three times in Picture 1, 2, 3 order.')
    args = parser.parse_args()
    if len(args.image_url) != 3:
        parser.error('Exactly three --image-url arguments are required.')
    for url in args.image_url:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            parser.error('Image URLs must be HTTPS URLs without embedded credentials.')
    root = Path(__file__).resolve().parent
    body = json.loads((root / 'fixtures' / 'h3_email_cases' /
                       f'case_{args.case}' / 'request.template.json').read_text())
    for item, url in zip(body['content'][1:], args.image_url):
        item['image_url'] = url
    sys.path.insert(0, str(root.parent))
    from cloudrun.schemas import CreateVideoRequest
    from cloudrun.validation import validate
    print(json.dumps(validate(CreateVideoRequest(**body)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
