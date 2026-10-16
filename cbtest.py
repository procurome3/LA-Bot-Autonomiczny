import unittest
from datetime import datetime, timedelta
from cb import  ready_to_run_cb


class TestReadyToRunCB(unittest.TestCase):
    def test_execution_within_timeframe(self):
        file_path = './textfiles/last_execution.txt'

        # create timestamp in test test file with yesterday time of execution
        execution_time = datetime(2023, 6, 17, 12, 30, 0)
        with open(file_path, 'w') as file:
            file.write(execution_time.strftime("%d.%m.%Y %H:%M:%S"))
        
        # Test case 1: test if ready to run at 17.06.2023 23:30:00
        current_time = datetime(2023, 6, 17, 23, 30, 0)
        expected_result = False # Don't expect to run again today
        self.assertEqual(ready_to_run_cb(file_path, current_time), expected_result)

        # Test case 2: test if ready to run at 18.06.2023 1:30:00
        current_time = datetime(2023, 6, 18, 1, 30, 0)
        expected_result = False
        self.assertEqual(ready_to_run_cb(file_path, current_time), expected_result)

        # Test case 3: test if ready to run at 18.06.2023 12:30:00
        current_time = datetime(2023, 6, 18, 12, 30, 0)
        expected_result = True
        self.assertEqual(ready_to_run_cb(file_path, current_time), expected_result)


class TestReadyToRun(unittest.TestCase):
    def test_execution_within_timeframe(self):
        file_path = './textfiles/last_execution.txt'

        # create timestamp in test test file with yesterday time of execution
        execution_time = datetime(2023, 6, 17, 12, 30, 0)
        with open(file_path, 'w') as file:
            file.write(execution_time.strftime("%d.%m.%Y %H:%M:%S"))
        
        # Test case 1: test if ready to run at 17.06.2023 23:30:00
        current_time = datetime(2023, 6, 17, 23, 30, 0)
        expected_result = False # Don't expect to run again today
        self.assertEqual(ready_to_run_cb(file_path, current_time), expected_result)

        # Test case 2: test if ready to run at 18.06.2023 1:30:00
        current_time = datetime(2023, 6, 18, 1, 30, 0)
        expected_result = False
        self.assertEqual(ready_to_run_cb(file_path, current_time), expected_result)

        # Test case 3: test if ready to run at 18.06.2023 12:30:00
        current_time = datetime(2023, 6, 18, 12, 30, 0)
        expected_result = True
        self.assertEqual(ready_to_run_cb(file_path, current_time), expected_result)



if __name__ == '__main__':
    unittest.main()


""" class TestReadyToRunCB(unittest.TestCase):
    def test_execution_within_timeframe(self):
        file_path = './textfiles/last_execution.txt'
        execution_time = datetime(2023, 6, 17, 12, 30, 0)
        with open(file_path, 'w') as file:
            file.write(execution_time.strftime("%d.%m.%Y %H:%M:%S"))
        
        # Test case 1: Execution at 17.06.2023 23:30:00
        current_time = datetime(2023, 6, 17, 23, 30, 0)
        expected_result = False
        self.assertEqual(__ready_to_run_cb(file_path), expected_result)

        # Test case 2: Execution at 18.06.2023 11:30:00
        current_time = datetime(2023, 6, 18, 11, 30, 0)
        expected_result = False
        self.assertEqual(__ready_to_run_cb(file_path), expected_result)

        # Test case 3: Execution at 18.06.2023 12:30:00
        current_time = datetime(2023, 6, 18, 12, 30, 0)
        expected_result = True
        self.assertEqual(__ready_to_run_cb(file_path), expected_result)

if __name__ == '__main__':
    unittest.main() """

