from __future__ import annotations

from models.base import StrictModel
from models.enums import Role


class TeamMember(StrictModel):
    id: str
    name: str
    role: Role
    skills: list[str] = []
    capacity_hours_per_sprint: float


class Team(StrictModel):
    members: list[TeamMember]

    def get(self, member_id: str):
        return next((m for m in self.members if m.id == member_id), None)

    def by_role(self, role: Role) -> list[TeamMember]:
        return [m for m in self.members if m.role == role]

    def ids(self) -> set[str]:
        return {m.id for m in self.members}

    @property
    def total_capacity(self) -> float:
        return sum(m.capacity_hours_per_sprint for m in self.members)

    def pool_capacity(self) -> dict:
        out: dict = {}
        for m in self.members:
            out[m.role] = out.get(m.role, 0.0) + m.capacity_hours_per_sprint
        return out
