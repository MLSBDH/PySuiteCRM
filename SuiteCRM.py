"""SuiteCRM API V8 client library."""
import atexit
import json
import math
import uuid
from urllib.parse import quote
from typing import Optional, Any

from oauthlib.oauth2 import (BackendApplicationClient,
                             TokenExpiredError,
                             InvalidClientError)
from oauthlib.oauth2.rfc6749.errors import CustomOAuth2Error
from requests_oauthlib import OAuth2Session
from .config_parser import PySuiteCRMConfig, PySuiteCRMConfigException


class SuiteCRM:
    """The main client class."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        url: Optional[str] = None,
        config: Optional[PySuiteCRMConfig] = None,
        logout_on_exit: bool = False
    ):
        """Initialize the client and connect to the API."""
        self.config: PySuiteCRMConfig
        if config:
            self.config = config
        else:
            if client_id and url and client_secret:
                self.config = PySuiteCRMConfig(
                    url=url,
                    client_id=client_id,
                    client_secret=client_secret
                )
        if not self.config:
            raise PySuiteCRMConfigException('No valid config found.')
        self._logout_on_exit = logout_on_exit
        self._headers = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
                        AppleWebKit/537.36 (KHTML, like Gecko) \
                        Chrome/97.0.4692.99 Safari/537.36'
        self._login()
        self._modules()

    def _modules(self):
        self.Accounts = Module(self, 'Accounts')
        self.Bugs = Module(self, 'Bugs')
        self.Calendar = Module(self, 'Calendar')
        self.Calls = Module(self, 'Calls')
        self.Cases = Module(self, 'Cases')
        self.Campaigns = Module(self, 'Campaigns')
        self.Contacts = Module(self, 'Contacts')
        self.Documents = Module(self, 'Documents')
        self.Email = Module(self, 'Email')
        self.Emails = Module(self, 'Emails')
        self.Employees = Module(self, 'Employees')
        self.Leads = Module(self, 'Leads')
        self.Lists = Module(self, 'Lists')
        self.Meetings = Module(self, 'Meetings')
        self.Notes = Module(self, 'Notes')
        self.Opportunities = Module(self, 'Opportunities')
        self.Projects = Module(self, 'Projects')
        self.Spots = Module(self, 'Spots')
        self.Surveys = Module(self, 'Surveys')
        self.Target = Module(self, 'Target')
        self.Targets = Module(self, 'Targets')
        self.Tasks = Module(self, 'Tasks')
        self.Templates = Module(self, 'Templates')

        self._load_custom_modules()

    def _load_custom_modules(self) -> None:
        """Load the custom modules from the config."""
        if not self.config.custom_modules:
            return

        for _module in self.config.custom_modules:
            try:
                if hasattr(self, _module['client_name']):
                    Warning('Attempted to load %s module multiple times!' %
                            _module['client_name'])
                    continue
                setattr(
                    self,
                    _module['client_name'],
                    Module(self, _module['crm_name'])
                )
            except AttributeError:
                Warning('Could not load %s module.' % _module['client_name'])

    def _refresh_token(self) -> None:
        """
        Fetch a new token from from token access url, specified in config file.

        :return: None
        """
        print(self.config)
        tk_url = self.config.url[:-2] + 'access_token'
        print(tk_url)
        try:
            self.OAuth2Session.fetch_token(
                token_url=tk_url,
                client_id=self.config.client_id,
                client_secret=self.config.client_secret
            )
        except InvalidClientError:
            exit('401 (Unauthorized) - client id/secret')
        except CustomOAuth2Error:
            exit('401 (Unauthorized) - client id')
        # Update configuration file with new token'
        with open('AccessToken.txt', 'w+') as file:
            file.write(str(self.OAuth2Session.token))

    def _login(self) -> None:
        """
        Login to the API.

        Checks to see if a Oauth2 Session exists, if not builds a session and
        retrieves the token from the config file, if no token in config file,
        fetch a new one.

        :return: None
        """
        # Does session exist?
        if not hasattr(self, 'OAuth2Session'):
            client = BackendApplicationClient(client_id=self.config.client_id)
            self.OAuth2Session = OAuth2Session(client=client,
                                               client_id=self.config.client_id)
            self.OAuth2Session.headers.update(
                {"User-Agent": self._headers,
                 'Content-Type': 'application/json'}
            )
            with open('AccessToken.txt', 'w+') as file:
                token = file.read()
                if token == '':
                    self._refresh_token()
                else:
                    self.OAuth2Session.token = token
        else:
            self._refresh_token()

        # Logout on exit
        if self._logout_on_exit:
            atexit.register(self._logout)

    def _logout(self) -> None:
        """
        Log out current Oauth2 Session.

        :return: None
        """
        url = '/logout'
        self.request(f'{self.config.url}{url}', 'post')
        with open('AccessToken.txt', 'w+') as file:
            file.write('')

    def request(self, url: str, method, parameters='') -> Optional[dict]:
        """
        Make a request to the given url with a specific method and data.

        If the request fails because the token expired the session will
        re-authenticate and attempt the request again with a new token.

        :param url: (string) The url
        :param method: (string) Get, Post, Patch, Delete
        :param parameters: (dictionary) Data to be posted

        :return: (dictionary) Data
        """
        url = quote(url, safe='/:?=&')
        data = json.dumps({"data": parameters})
        try:
            the_method = getattr(self.OAuth2Session, method)
        except AttributeError:
            return

        try:
            if parameters == '':
                data = the_method(url)
            else:
                data = the_method(url, data=data)
        except TokenExpiredError:
            self._refresh_token()
            if parameters == '':
                data = the_method(url)
            else:
                data = the_method(url, data=data)

        # Revoked Token
        attempts = 0
        while data.status_code == 401 and attempts < 1:
            self._refresh_token()
            if parameters == '':
                data = the_method(url)
            else:
                data = the_method(url, data=data)
            attempts += 1
        if data.status_code == 401:
            exit(
                '401 (Unauthorized) client id/secret has been revoked, \
                new token was attempted and failed.'
            )

        # Database Failure
        # SuiteCRM does not allow to query by a custom field
        # See README,#Limitations
        if data.status_code == 400 and \
                'Database failure.' in data.content.decode():
            raise Exception(data.content.decode())

        return json.loads(data.content)


class Module:
    """The module class."""

    def __init__(self, suitecrm, module_name):
        """Initialize the module class."""
        self.module_name = module_name
        self.suitecrm = suitecrm

    def create(self, **attributes) -> dict:
        """
        Create a record with given attributes.

        :param attributes: (**kwargs) fields with data you want to
            populate the record with.

        :return: (dictionary) The record that was created with the attributes.
        """
        url = '/module'
        data = {'type': self.module_name, 'id': str(
            uuid.uuid4()), 'attributes': attributes}
        return self.suitecrm.request(
            f'{self.suitecrm.config.url}{url}',
            'post',
            data
        )

    def delete(self, record_id: str) -> dict:
        """
        Delete a specific record by id.

        :param record_id: (string) The record id within the module to delete.

        :return: (dictionary) Confirmation of deletion of record.
        """
        # Delete
        url = f'/module/{self.module_name}/{record_id}'
        return self.suitecrm.request(
            f'{self.suitecrm.config.url}{url}',
            'delete'
        )

    def fields(self) -> list:
        """
        Get all the attributes that can be set in a record.

        :return: (list) All the names of attributes in a record.
        """
        # Get total record count
        url = f'/module/{self.module_name}?page[number]=1&page[size]=1'
        return list(
            self.suitecrm.request(
                f'{self.suitecrm.config.url}{url}',
                'get'
            )['data'][0]['attributes'].keys()
        )

    def get(
        self,
        fields: Optional[list[str]] = None,
        sort: str = '',
        **filters
    ) -> list:
        """
        Get records given a specific id or filters.

        Can be sorted only once, and the fields returned for each record
        can be specified.

        :param fields: (list) A list of fields to be returned from each record.
        :param sort: (string) The field to sort the records by.
        :param filters: (**kwargs) fields to filter on.
                        ie... date_start= {'operator': '>',
                        'value':'2020-05-08T09:59:00+00:00'}

        Important notice: we don’t support multiple level sorting right now!

        :return: (list) A list of dictionaries records.
        """
        # Fields Constructor
        if fields:
            _fields = f'?fields[{self.module_name}]=' + ','.join(fields)
            url = f'/module/{self.module_name}{_fields}&filter'
        else:
            url = f'/module/{self.module_name}?filter'

        # Filter Constructor
        operators = {'=': 'EQ', '<>': 'NEQ', '>': 'GT',
                     '>=': 'GTE', '<': 'LT', '<=': 'LTE'}
        for field, value in filters.items():
            if isinstance(value, dict):
                url = ''.join([
                    url,
                    f'[{field}]',
                    f'[{operators[value["operator"]]}]',
                    f'={value["value"]}and&'
                ])
            else:
                url = f'{url}[{field}][eq]={value}and&'
        url = url[:-4]

        # Sort
        if sort:
            url = f'{url}&sort=-{sort}'

        # Execute
        return self.suitecrm.request(
            f'{self.suitecrm.config.url}{url}',
            'get'
        )['data']

    def get_all(self, record_per_page: int = 100) -> list:
        """
        Get all the records in the module.

        :return: (list) A list of records as dictionaries.
                 Will return all records within a module.
        """
        # Get total record count
        url = f'/module/{self.module_name}?page[number]=1&page[size]=1'
        req = self.suitecrm.request(
            f'{self.suitecrm.config.url}{url}',
            'get'
        )
        if 'total-pages' not in req['meta']:
            return []
        pages = math.ceil(
            req['meta']['total-pages'] / record_per_page
        ) + 1
        result = []
        for page in range(1, pages):
            url = '/'.join([
                '/module',
                self.module_name]) + '&'.join([
                    f'?page[number]={page}',
                    f'page[size]={record_per_page}'
                ])
            result.extend(self.suitecrm.request(
                f'{self.suitecrm.config.url}{url}', 'get')['data'])
        return result

    def update(self, record_id: str, **attributes) -> dict:
        """
        Update a record.

        :param record_id: (string) id of the current module record.
        :param attributes: (**kwargs) fields of the record to be updated.

        :return: (dictionary) The updated record
        """
        url = '/module'
        data = {'type': self.module_name,
                'id': record_id, 'attributes': attributes}
        return self.suitecrm.request(
            f'{self.suitecrm.config.url}{url}',
            'patch',
            data
        )

    def get_relationship(
        self,
        record_id: str,
        related_module_name: str
    ) -> dict:
        """
        Return the relationship between this record and another module.

        :param record_id: (string) id of the current module record.
        :param related_module_name: (string) the module name to search \
            relationships for, ie. Contacts.

        :return: (dictionary) A list of relationships that this module's \
            record contains with the related module.
        """
        url = '/'.join([
            '/module',
            self.module_name,
            record_id,
            'relationships',
            related_module_name.lower()
        ])
        return self.suitecrm.request(f'{self.suitecrm.config.url}{url}', 'get')['data']

    def create_relationship(
        self,
        record_id: str,
        related_module_name: str,
        related_bean_id: str
    ) -> dict:
        """
        Create a relationship between 2 records.

        :param record_id: (string) id of the current module record.
        :param related_module_name: (string) the module name of the record \
            of which to create a relationship, ie. Contacts.
        :param related_bean_id: (string) id of the related record.

        :return: (dictionary) A record that the relationship was created.
        """
        # Post
        url = f'/module/{self.module_name}/{record_id}/relationships'
        data = {
            'type': related_module_name.capitalize(),
            'id': related_bean_id
        }
        return self.suitecrm.request(
            f'{self.suitecrm.config.url}{url}',
            'post',
            data
        )

    def delete_relationship(
        self,
        record_id: str,
        related_module_name: str,
        related_bean_id: str
    ) -> dict:
        """
        Delete a relationship between 2 records.

        :param record_id: (string) id of the current module record.
        :param related_module_name: (string) the related record's module \
            name, ie. Contacts.
        :param related_bean_id: (string) id of the related record.

        :return: (dictionary) A record that the relationship was deleted.
        """
        url = '/'.join([
            'module',
            self.module_name,
            record_id,
            'relationships',
            related_module_name.lower(),
            related_bean_id
        ])
        return self.suitecrm.request(
            f'{self.suitecrm.config.url}{url}',
            'delete'
        )
