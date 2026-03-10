from dataclasses import dataclass


@dataclass
class Project:
    name: str
    thread_id: int | None = None

    @property
    def thread_name(self) -> str:
        return f"project: {self.name}"

    def to_dict(self) -> dict:
        data = {}
        if self.thread_id is not None:
            data["thread_id"] = self.thread_id
        return data

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "Project":
        return cls(
            name=name,
            thread_id=data.get("thread_id"),
        )
