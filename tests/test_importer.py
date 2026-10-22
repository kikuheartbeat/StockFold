import unittest
from .test_records import DatabaseFixture
from app.importer import preview_xlsx
from app.validation import ValidationError


class ImporterTest(DatabaseFixture):


    def test_invalid_archive_rejected(self):
        with self.assertRaises(ValidationError): preview_xlsx(self.conn,b'not a workbook','x.xlsx')



if __name__=='__main__': unittest.main()
