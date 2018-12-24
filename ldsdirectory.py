import os
import argparse
from dataclasses import dataclass
from typing import Optional

from ldsapi import Client
from dotenv import load_dotenv
from jinja2 import Template


TEMPLATE_FILE_PATH = 'files/template.j2'


@dataclass
class Member:
    id: int
    member_number: str
    given_name: str
    surname: str
    preferred_name: str
    email: str
    phone: str
    address_parts: [str]
    calling: Optional[str]
    image_path: Optional[str]

    @property
    def formatted_name(self):
        parts = self.preferred_name.split(',')
        parts = [part.strip() for part in parts]
        parts = reversed(parts)

        return ' '.join(parts)

    @property
    def formatted_calling(self):
        if self.calling:
            return self.calling

        return '<i>No calling</i>'

    @staticmethod
    def from_json(data: dict, calling: Optional[str]):
        address_parts = [
            data['desc1'],
            data['desc2'],
            data['desc3'],
            data['desc4'],
            data['desc5'],
        ]
        address_parts = list(filter(lambda x: x, address_parts))

        return Member(
            id=data['headOfHouse']['individualId'],
            member_number=data['headOfHouse']['memberId'],
            given_name=data['headOfHouse']['givenName1'],
            surname=data['headOfHouse']['surname'],
            preferred_name=data['headOfHouse']['preferredName'],
            email=data['headOfHouse']['email'],
            phone=data['headOfHouse']['phone'],
            address_parts=address_parts,
            calling=calling,
            image_path=None,
        )


class Directory:
    def __init__(self, members: list):
        self.members = members

    def generate(self):
        with open(TEMPLATE_FILE_PATH) as file:
            template_file = file.read()

        return Template(template_file).render(members=self.members)


class DataFetcher:
    def __init__(self, output_dir):
        load_dotenv()

        self._output_dir = output_dir
        self._cache_dir = os.path.join(output_dir, 'cache')

        user = os.getenv('LDS_USER')
        password = os.getenv('LDS_PASSWORD')

        if not user or not password:
            raise Exception('User or password not set')

        self._client = Client(user, password)

        self._members = {}
        self._ids = []

    @property
    def members(self):
        return list(self._members.values())

    def load_members(self):
        data = self._client.get('unit-members-and-callings').json()

        ids_to_calling = {}
        for calling in data['callings']:
            ids_to_calling[calling['individualId']] = calling['callingName']

        members = [
            Member.from_json(
                data,
                ids_to_calling.get(str(data['headOfHouse']['individualId'])),
            ) 
            for data in data['households']
        ]
        for member in members:
            self._members[str(member.id)] = member

        self._ids = [str(member['headOfHouse']['individualId'])
           for member in data['households']]

    def load_member_images(self, download, override):
        if not os.path.exists(self._cache_dir):
            os.makedirs(self._cache_dir)

        if download:
            self._download_images(override)

        downloaded_ids = [entry.replace('.jpg', '')
                          for entry in os.listdir(self._cache_dir)]

        for id in downloaded_ids:
            if id in self._members:
                self._members[id].image_path = os.path.join(
                    self._cache_dir, f'{id}.jpg')

    def _download_images(self, override):
        if not override:
            downloaded_ids = [entry.replace('.jpg', '')
                              for entry in os.listdir(self._cache_dir)]
        else:
            downloaded_ids = []

        missing_ids = set(self._ids) - set(downloaded_ids)    
    
        data = self._client.get(
            'photo-url',
            'individual',
            member=','.join(missing_ids)
        ).json()

        for photo_data in data:
            if photo_data['largeUri']:
                id = str(photo_data['individualId'])
                file_path = os.path.join(self._cache_dir, f'{id}.jpg')
                url = photo_data['largeUri']
                self._download_file(file_path, url)

    def _download_file(self, file_path, url):
        res = self._client.session.get(url, stream=True)
        with open(file_path, 'wb') as f:
            for chunk in res.iter_content(chunk_size=1024): 
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)
                    f.flush()

    def close(self):
        self._client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='LDS directory maker.')
    parser.add_argument(
        '--output-dir',
        default='output',
        type=str,
        help='destination of output files'
    )
    parser.add_argument(
        '--download-images',
        default=False,
        action='store_true',
        help='Download member images',
    )
    parser.add_argument(
        '--override-images',
        default=False,
        action='store_true',
        help='Override downloaded member images',
    )

    args = parser.parse_args()
    output_dir = os.path.abspath(args.output_dir)
    download_images = args.download_images
    override_images = args.override_images

    fetcher = DataFetcher(output_dir)
    fetcher.load_members()
    fetcher.load_member_images(download_images, override_images)
    fetcher.close()

    directory = Directory(fetcher.members)
    output = directory.generate()

    with open(os.path.join(output_dir, 'index.html'), 'w') as file:
        file.write(output)
        file.flush()
