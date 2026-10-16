from datetime import datetime, timedelta

def write_execution_status(file_path):
    current_datetime = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with open(file_path, 'w') as file:
        file.write(current_datetime)


def ready_to_run_cb(file_path, current_time=None):
    try:
        with open(file_path, 'r') as file:
            execution_datetime_str = file.read().strip()
            executed_last_time = datetime.strptime(execution_datetime_str, "%d.%m.%Y %H:%M:%S")
            current_datetime = current_time or datetime.now()
            if current_datetime.hour >= 12:
                current_time_frame_start = datetime(
                    current_datetime.year, current_datetime.month, current_datetime.day, 12, 0, 0
                )
            else:
                previous_day = current_datetime - timedelta(days=1)
                current_time_frame_start = datetime(
                    previous_day.year, previous_day.month, previous_day.day, 12, 0, 0
                )
            time_frame_end = current_time_frame_start + timedelta(days=1) - timedelta(seconds=1)
            if current_time_frame_start <= executed_last_time <= time_frame_end:
                print("Allready did run today")
                return False
            else:
                print("Ready to run")
                return True
    except FileNotFoundError:
        return False




""" def ready_to_run_cb(file_path, current_time=None):
    try:
        with open(file_path, 'r') as file:
            execution_datetime = file.read().strip()
            executed_last_time = datetime.strptime(execution_datetime, "%d.%m.%Y %H:%M:%S")
            current_datetime = current_time or datetime.now()
            today_start = datetime(current_datetime.year, current_datetime.month, current_datetime.day, 12, 0, 0)
            next_day_end = today_start + timedelta(days=1) - timedelta(seconds=1)

            print("executed last time: ", executed_last_time)
            print("current_datetime:   ", current_datetime)
            print("today_start:        ", today_start)
            print("next_day_end:       ", next_day_end)
            print("____")
            print(" today_start <= executed_last_time ", today_start <= executed_last_time)
            print(" executed_last_time <= next_day_end ", executed_last_time <= next_day_end)


            if today_start <= executed_last_time <= next_day_end:
                print("Allready did run today")
                return False
            else:
                print("Ready to run")
                return True
    except FileNotFoundError:
        print("3")
        return False """





""" def ready_to_run_cb(file_path):
    try:
        with open(file_path, 'r') as file:
            execution_datetime = file.read().strip()
            execution_datetime = datetime.strptime(execution_datetime, "%d.%m.%Y %H:%M:%S")
            current_datetime = datetime.now()
            next_day_start = datetime(current_datetime.year, current_datetime.month, current_datetime.day + 1, 12, 0, 0)
            if execution_datetime < next_day_start:
                return True
            else:
                return False
    except FileNotFoundError:
        return False """

""" def ready_to_run_cb(file_path):
    try:
        with open(file_path, 'r') as file:
            execution_datetime = file.read().strip()
            execution_datetime = datetime.strptime(execution_datetime, "%Y-%m-%d %H:%M:%S")
            current_datetime = datetime.now()
            today_start = datetime(current_datetime.year, current_datetime.month, current_datetime.day, 12, 0, 0)
            next_day_end = datetime(current_datetime.year, current_datetime.month, current_datetime.day + 1, 11, 59, 59)
            if execution_datetime >= today_start and execution_datetime <= next_day_end:
                return True
            else:
                return False
    except FileNotFoundError:
        return False """