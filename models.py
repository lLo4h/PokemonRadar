from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Product:
    shop: str
    product_id: str
    title: str
    url: str
    price: str | None
    status: str
    is_preorder: bool = False
    image_url: str | None = None

    def __post_init__(self) -> None:
        allowed_statuses = {"available", "unavailable", "unknown"}
        if self.status not in allowed_statuses:
            raise ValueError(
                f"Ungültiger Status '{self.status}'. Erlaubt: {sorted(allowed_statuses)}"
            )
