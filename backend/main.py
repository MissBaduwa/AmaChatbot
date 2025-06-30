from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import db_helper
import generic_helper

app = FastAPI()

inprogress_orders = {}

@app.get("/")
async def root():
    return {"message": "Webhook server is live!"}

@app.post("/")
async def handle_request(request: Request):
    payload = await request.json()
    print(f"Incoming payload: {payload}")

    try:
        intent = payload['queryResult']['intent']['displayName']
        parameters = payload['queryResult']['parameters']
        output_contexts = payload['queryResult']['outputContexts']
        session_id = generic_helper.extract_session_id(output_contexts[0]["name"])

        intent_handler_dict = {
            'order.add - context: ongoing-order': add_to_order,
            'order.remove - context: ongoing-order': remove_from_order,
            'order.complete - context: ongoing-order': complete_order,
            'track.order - context: ongoing-tracking': track_order
        }

        if intent in intent_handler_dict:
            return intent_handler_dict[intent](parameters, session_id)
        else:
            return JSONResponse(content={"error": "Unhandled intent"}, status_code=400)
    except Exception as e:
        print("❌ Exception in webhook:", e)
        return JSONResponse(content={"error": str(e)}, status_code=500)


def save_to_db(order: dict):
    next_order_id = db_helper.get_next_order_id()
    for food_item, quantity in order.items():
        if db_helper.insert_order_item(food_item, quantity, next_order_id) == -1:
            return -1
    db_helper.insert_order_tracking(next_order_id, "in progress")
    return next_order_id


def complete_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        return JSONResponse(content={
            "fulfillmentText": "I'm having a trouble finding your order. Can you place a new order please?"
        })

    order = inprogress_orders[session_id]
    order_id = save_to_db(order)
    if order_id == -1:
        fulfillment_text = "Sorry, I couldn't process your order due to a backend error."
    else:
        order_total = db_helper.get_total_order_price(order_id)
        fulfillment_text = f"Awesome! Your order is placed. Here is your order id #{order_id}. " \
                           f"Your total is {order_total} — pay on delivery."
    del inprogress_orders[session_id]

    return JSONResponse(content={"fulfillmentText": fulfillment_text})


def add_to_order(parameters: dict, session_id: str):
    food_items = parameters.get("food-item", [])
    quantities = parameters.get("number", [])

    if len(food_items) != len(quantities):
        fulfillment_text = "Sorry, I didn't understand. Please specify food items and quantities clearly."
    else:
        new_items = dict(zip(food_items, quantities))
        order = inprogress_orders.get(session_id, {})
        for item, qty in new_items.items():
            order[item] = order.get(item, 0) + int(qty)
        inprogress_orders[session_id] = order

        order_str = generic_helper.get_str_from_food_dict(order)
        fulfillment_text = f"So far, your order includes: {order_str}. Do you need anything else?"

    return JSONResponse(content={"fulfillmentText": fulfillment_text})


def remove_from_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        return JSONResponse(content={
            "fulfillmentText": "I'm having trouble finding your order. Please start a new order."
        })

    food_items = parameters.get("food-item", [])
    quantities = parameters.get("number", [])
    order = inprogress_orders[session_id]

    removed_items = []
    no_such_items = []

    for idx, item in enumerate(food_items):
        if item not in order:
            no_such_items.append(item)
            continue

        # Default quantity to remove is 1 if not specified
        qty_to_remove = int(quantities[idx]) if idx < len(quantities) else 1
        current_qty = order[item]

        if qty_to_remove >= current_qty:
            del order[item]
            removed_items.append(f"all {item}")
        else:
            order[item] -= qty_to_remove
            removed_items.append(f"{qty_to_remove} {item}")

    if not removed_items:
        fulfillment_text = "Couldn't remove anything. Please double-check your order."
    else:
        fulfillment_text = f"Removed {', '.join(removed_items)} from your order."

    if no_such_items:
        fulfillment_text += f" Note: {', '.join(no_such_items)} was not found in your current order."

    if order:
        order_str = generic_helper.get_str_from_food_dict(order)
        fulfillment_text += f" Here's what's left: {order_str}"
    else:
        fulfillment_text += " Your order is now empty."

    return JSONResponse(content={
        "fulfillmentText": fulfillment_text
    })


    if not removed_items:
        fulfillment_text = "Couldn't remove anything. Please double-check your order."
    else:
        fulfillment_text = f"Removed {', '.join(removed_items)} from your order."

    if order:
        order_str = generic_helper.get_str_from_food_dict(order)
        fulfillment_text += f" Here's what's left: {order_str}"
    else:
        fulfillment_text += " Your order is now empty."

    inprogress_orders[session_id] = order
    return JSONResponse(content={"fulfillmentText": fulfillment_text})


def track_order(parameters, session_id):
    order_id = int(parameters.get("number", -1))
    if order_id == -1:
        return {"fulfillmentText": "Sorry, I couldn't find your order number."}

    status = db_helper.get_order_status(order_id)
    if status:
        return {"fulfillmentText": f"Your order #{order_id} is currently '{status}'."}
    else:
        return {"fulfillmentText": f"Sorry, no tracking info found for order #{order_id}."}
