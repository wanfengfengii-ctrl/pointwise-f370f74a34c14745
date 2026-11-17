from dataclasses import dataclass

class InvalidObservation(ValueError):
    pass

ObservationKey = tuple[str, int]

@dataclass(frozen=True)
class ObservationRecord:
    identity: str
    source_revision: int
    time: int
    symbol: str

    def to_data(self):
        return [self.identity, self.source_revision, self.time, self.symbol]

def validate_record(record):
    if not isinstance(record, ObservationRecord):
        raise InvalidObservation("expected ObservationRecord")
    if not isinstance(record.identity, str) or not record.identity:
        raise InvalidObservation("identity must be a nonempty string")
    if not isinstance(record.symbol, str) or not record.symbol:
        raise InvalidObservation("symbol must be a nonempty string")
    for number in (record.source_revision, record.time):
        if type(number) is not int or not -(2**63) <= number < 2**63:
            raise InvalidObservation("revision and time must be signed 64-bit integers")
    return record

def same_record_content(left, right):
    return left.to_data() == right.to_data()
