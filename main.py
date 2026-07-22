import logging

from opscalper.bot import OptionsScalper
from opscalper.config import Config

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OptionsScalper(Config()).run()
