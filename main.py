import os
from typing import List
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
import schemas
from auth import AuthServiceClient
from database import SessionLocal, engine, Base

from pythonjsonlogger import jsonlogger
import logging
import sys
import json

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
Base.metadata.create_all(bind=engine)
auth_service = AuthServiceClient()

# JSON logging setup
logHandler = logging.StreamHandler(sys.stdout)
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
logHandler.setFormatter(formatter)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logHandler)

# Dependency for getting the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        
# Adaugă următorul endpoint în main.py din idp_backend
@app.post("/register", response_model=schemas.UserOut)
def register_user(
    user_data: schemas.UserCreate, 
    db: Session = Depends(get_db)
):
    """
    Înregistrează un utilizator nou.
    """
    # Verifică dacă email-ul există deja
    existing_user = db.query(models.User).filter(models.User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Creează utilizatorul în serviciul de autentificare
    try:
        auth_user = auth_service.register(
            name=user_data.name,
            email=user_data.email,
            password=user_data.password
        )
        
        # Creează utilizatorul local cu ID-ul de la serviciul de autentificare
        db_user = models.User(
            id=auth_user.get("id"),
            name=user_data.name,
            email=user_data.email
        )
        
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        
        return db_user
    except Exception as e:
        # În caz de eroare, returnează eroarea de la serviciul de autentificare
        if hasattr(e, "detail"):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

# --- USER ENDPOINTS ---
@app.get("/users/me")
def read_users_me(user_id: int = Depends(auth_service.get_current_user_id), db: Session = Depends(get_db)):
    """
    Get current user information using the ID from the auth service
    """
    # Find the user by ID
    user = db.query(models.User).filter(models.User.id == user_id).first()
    # If user not found in our database, return minimal info
    if user is None:
        return {"id": user_id, "name": "Unknown User"}
    return user

@app.get("/users/", response_model=List[schemas.UserOut])
def read_users(user_id: int = Depends(auth_service.get_current_user_id), db: Session = Depends(get_db)):
    """
    List all users - requires authentication
    """
    # Now we only need user_id for authentication, not the full user object
    return db.query(models.User).all()

# --- PROTECTED CRUD ROUTES ---
@app.post("/products/", response_model=schemas.ProductOut)
def create_product(
        product: schemas.ProductCreate,
        db: Session = Depends(get_db),
        user_id: int = Depends(auth_service.get_current_user_id)
):
    """
    Create a product - requires authentication
    """
    db_product = models.Product(**product.dict())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

@app.get("/products/", response_model=List[schemas.ProductOut])
def get_products(db: Session = Depends(get_db), user_id: int = Depends(auth_service.get_current_user_id)):
    """
    List all products - requires authentication
    """
    return db.query(models.Product).all()

@app.get("/products/{product_id}", response_model=schemas.ProductOut)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(auth_service.get_current_user_id)
):
    """
    Get product details
    """
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

# --- BASKET ENDPOINTS ---
class BasketItemCreateRequest(BaseModel):
    product_id: int
    quantity: int

@app.get("/basket/", response_model=List[schemas.BasketItemOut])
def get_basket(user_id: int = Depends(auth_service.get_current_user_id), db: Session = Depends(get_db)):
    """
    Get current user's basket items
    """
    # Get all basket items for the current user
    basket_items = db.query(models.BasketItem).filter(models.BasketItem.user_id == user_id).all()
    
    # Return the basket items
    return basket_items

@app.post("/basket/", response_model=schemas.BasketItemOut)
def add_to_basket(
    item: BasketItemCreateRequest,
    user_id: int = Depends(auth_service.get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Add a product to the basket
    """
    # Verifică dacă produsul există
    product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Verifică stocul
    if product.stock < item.quantity:
        raise HTTPException(status_code=400, detail="Not enough stock available")
    
    # Verifică dacă produsul există deja în coș
    existing_item = db.query(models.BasketItem).filter(
        models.BasketItem.user_id == user_id,
        models.BasketItem.product_id == item.product_id
    ).first()
    
    if existing_item:
        # Actualizează cantitatea
        existing_item.quantity += item.quantity
        db.commit()
        db.refresh(existing_item)
        return existing_item
    
    # Creează un nou item în coș
    db_item = models.BasketItem(
        user_id=user_id,
        product_id=item.product_id,
        quantity=item.quantity
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.put("/basket/{basket_item_id}", response_model=schemas.BasketItemOut)
def update_basket_item(
    basket_item_id: int,
    quantity: int,
    user_id: int = Depends(auth_service.get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Update the quantity of a basket item
    """
    # Găsește itemul în coș
    basket_item = db.query(models.BasketItem).filter(
        models.BasketItem.id == basket_item_id,
        models.BasketItem.user_id == user_id
    ).first()
    
    if not basket_item:
        raise HTTPException(status_code=404, detail="Basket item not found")
    
    # Verifică stocul
    product = db.query(models.Product).filter(models.Product.id == basket_item.product_id).first()
    if product.stock < quantity:
        raise HTTPException(status_code=400, detail="Not enough stock available")
    
    # Actualizează cantitatea
    basket_item.quantity = quantity
    db.commit()
    db.refresh(basket_item)
    return basket_item

@app.delete("/basket/{basket_item_id}", status_code=204)
def remove_basket_item(
    basket_item_id: int,
    user_id: int = Depends(auth_service.get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Remove an item from the basket
    """
    # Găsește itemul în coș
    basket_item = db.query(models.BasketItem).filter(
        models.BasketItem.id == basket_item_id,
        models.BasketItem.user_id == user_id
    ).first()
    
    if not basket_item:
        raise HTTPException(status_code=404, detail="Basket item not found")
    
    # Șterge itemul
    db.delete(basket_item)
    db.commit()
    return None

@app.delete("/basket/", status_code=204)
def clear_basket(
    user_id: int = Depends(auth_service.get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Clear the basket (remove all items)
    """
    # Găsește toate itemele din coș
    basket_items = db.query(models.BasketItem).filter(models.BasketItem.user_id == user_id)
    
    # Șterge toate itemele
    basket_items.delete(synchronize_session=False)
    db.commit()
    return None

# --- ORDER ENDPOINTS ---
class CreateOrderRequest(BaseModel):
    shipping_address: Optional[str] = None
    payment_method: Optional[str] = None

@app.get("/orders/", response_model=List[schemas.OrderOut])
def get_orders(user_id: int = Depends(auth_service.get_current_user_id), db: Session = Depends(get_db)):
    """
    Get all orders for the current user
    """
    orders = db.query(models.Order).filter(models.Order.user_id == user_id).all()
    for order in orders:
        # Asigură-te că există relația items
        if not hasattr(order, 'items'):
            order.items = []
    return orders

@app.get("/orders/{order_id}", response_model=schemas.OrderOut)
def get_order(
    order_id: int,
    user_id: int = Depends(auth_service.get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get details of a specific order
    """
    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.user_id == user_id
    ).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Asigură-te că există relația items
    if not hasattr(order, 'items'):
        order.items = []
    
    return order

@app.post("/orders/", response_model=schemas.OrderOut)
def create_order(
    order_data: CreateOrderRequest,
    user_id: int = Depends(auth_service.get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Create a new order from basket items
    """
    # Verifică dacă există iteme în coș
    basket_items = db.query(models.BasketItem).filter(models.BasketItem.user_id == user_id).all()
    if not basket_items:
        raise HTTPException(status_code=400, detail="Basket is empty")
    
    # Calculează totalul
    total = 0
    for item in basket_items:
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        
        if product.stock < item.quantity:
            raise HTTPException(status_code=400, detail=f"Not enough stock for product {product.name}")
        
        total += float(product.price) * item.quantity
    
    # Creează comanda
    db_order = models.Order(
        user_id=user_id,
        total=total
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    
    # Adaugă produsele în comandă
    for item in basket_items:
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        
        # Adaugă itemul în comandă
        order_item = models.OrderItem(
            order_id=db_order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            price_at_purchase=product.price
        )
        db.add(order_item)
        
        # Actualizează stocul
        product.stock -= item.quantity
        
        # Șterge itemul din coș
        db.delete(item)
    
    db.commit()
    return db_order

@app.post("/orders/{order_id}/cancel", response_model=schemas.OrderOut)
def cancel_order(
    order_id: int,
    user_id: int = Depends(auth_service.get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Cancel an order
    """
    # Găsește comanda
    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.user_id == user_id
    ).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Returnează produsele în stoc
    order_items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order_id).all()
    for item in order_items:
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if product:
            product.stock += item.quantity
    
    db.commit()
    db.refresh(order)
    return order
