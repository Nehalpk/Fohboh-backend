import pandas as pd
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)

# Define minimum required columns for each category
# IMPORTANT: Column names should match your actual CSV columns (case-insensitive, with spaces)
MINIMUM_REQUIRED_COLUMNS = {
    "Labor": {
        "required": ["date", "hours worked"],  # ✅ Changed "hours_worked" to "hours worked"
        "at_least_one": [
            ["position", "role"],  # ✅ Must have either Position OR Role (they're the same)
            ["hourly rate", "total wages"]  # ✅ Must have either pay rate
        ],
        "recommended": ["employee id", "name", "regular hours", "overtime hours"]
    },
    "Inventory": {
        "required": ["date", "ingredient", "quantity"],
        "at_least_one": [["unit cost", "total value"]],  # ✅ Changed "unit_cost" to "unit cost"
        "recommended": ["category", "unit of measure", "par level"]  # ✅ Changed to match CSV
    },
    "Sales": {
        "required": ["date"],
        "at_least_one": [["total amount", "subtotal", "total sales", "revenue"]],  # ✅ Added actual column names
        "recommended": ["sale id", "items sold", "order type", "payment method"]  # ✅ Changed to match CSV
    },
    "Menu": {
        "required": ["menu item"],  # ✅ Changed "item_name" to "menu item"
        "at_least_one": [["item price", "unit cost"]],  # ✅ Changed to match CSV
        "recommended": ["category", "ingredient", "amount"]  # ✅ Changed to match CSV
    }
}

def validate_csv_columns(
    file_content: bytes,
    category: str,
    filename: str
) -> Tuple[bool, Dict]:
    """
    Validate that CSV has minimum required columns for the category.
    
    Args:
        file_content: Raw bytes of the CSV file
        category: Category name (Labor, Inventory, Sales, Menu)
        filename: Name of the file being validated
        
    Returns:
        Tuple of (is_valid, result_dict)
        result_dict contains:
            - status: "success" or "error"
            - message: Description of validation result
            - missing_required: List of missing required columns
            - missing_at_least_one: Groups where at least one column is needed
            - found_columns: List of columns found in the file
            - recommendations: Suggested columns to add
    """
    try:
        # Validate category
        if category not in MINIMUM_REQUIRED_COLUMNS:
            return False, {
                "status": "error",
                "message": f"Invalid category: {category}. Must be one of: {', '.join(MINIMUM_REQUIRED_COLUMNS.keys())}",
                "valid_categories": list(MINIMUM_REQUIRED_COLUMNS.keys())
            }
        
        # Read CSV to get column names
        import io
        df = pd.read_csv(io.BytesIO(file_content), nrows=0)
        found_columns = [col.strip().lower() for col in df.columns]
        
        logger.info(f"Validating {filename} for category {category}")
        logger.info(f"Found columns: {found_columns}")
        
        # Get requirements for this category
        requirements = MINIMUM_REQUIRED_COLUMNS[category]
        required_cols = [col.lower() for col in requirements["required"]]
        at_least_one_groups = requirements.get("at_least_one", [])
        recommended_cols = [col.lower() for col in requirements.get("recommended", [])]
        
        # Check required columns
        missing_required = []
        for req_col in required_cols:
            if req_col not in found_columns:
                missing_required.append(req_col)
        
        # Check "at least one" groups
        missing_at_least_one = []
        for group in at_least_one_groups:
            group_lower = [col.lower() for col in group]
            if not any(col in found_columns for col in group_lower):
                missing_at_least_one.append(group)
        
        # Check recommended columns
        missing_recommended = []
        for rec_col in recommended_cols:
            if rec_col not in found_columns:
                missing_recommended.append(rec_col)
        
        # Determine if validation passed
        is_valid = len(missing_required) == 0 and len(missing_at_least_one) == 0
        
        if is_valid:
            return True, {
                "status": "success",
                "message": f"✅ File '{filename}' has all required columns for {category} category",
                "found_columns": found_columns,
                "missing_recommended": missing_recommended,
                "recommendation_message": f"Consider adding these columns for better analysis: {', '.join(missing_recommended)}" if missing_recommended else "All recommended columns are present!"
            }
        else:
            # Build detailed error message
            error_parts = []
            
            if missing_required:
                error_parts.append(
                    f"❌ Missing required columns: {', '.join(missing_required)}"
                )
            
            if missing_at_least_one:
                for group in missing_at_least_one:
                    error_parts.append(
                        f"❌ Must have at least ONE of these columns: {' OR '.join(group)}"
                    )
            
            error_message = f"File '{filename}' is missing required columns for {category} category:\n\n" + "\n".join(error_parts)
            
            return False, {
                "status": "error",
                "message": error_message,
                "category": category,
                "filename": filename,
                "found_columns": found_columns,
                "missing_required": missing_required,
                "missing_at_least_one": missing_at_least_one,
                "missing_recommended": missing_recommended,
                "required_columns": required_cols,
                "example_fix": get_example_columns(category)
            }
            
    except pd.errors.EmptyDataError:
        return False, {
            "status": "error",
            "message": f"File '{filename}' is empty or has no data",
            "category": category
        }
    except Exception as e:
        logger.error(f"Error validating CSV columns: {str(e)}")
        return False, {
            "status": "error",
            "message": f"Error reading file: {str(e)}",
            "category": category
        }

def get_example_columns(category: str) -> Dict:
    """Get example column structure for a category"""
    examples = {
        "Labor": {
            "example_headers": "Date,Employee ID,Name,Position,Hours Worked,Hourly Rate,Is Salaried,Shift Start,Shift End,Is Overtime,Department,Overtime Hours",
            "note": "You can use either 'Position' or 'Role' column (they're the same)",
            "sample_row": "25/10/2025,101,John Smith,Server,8,15,FALSE,9:00:00,17:00:00,FALSE,Front of House,3"
        },
        "Inventory": {
            "example_headers": "Date,Ingredient,Quantity,Par Level,Unit Cost,Is Low,Unit of Measure,Supplier,Last Ordered Date",
            "sample_row": "30/10/2025,Flour,45,50,2.5,TRUE,lb,ABC Foods,25/10/2025"
        },
        "Sales": {
            "example_headers": "Date,Sale ID,Time,Items Sold,Number of Items,Subtotal,Tip,Total Amount,Employee ID,Is Loyalty Member,Promotion ID,Discount Percent,Order Type,Payment Method,Covers",
            "sample_row": "25/10/2025,S001,12:30:00,Pizza;Salad;Soda,3,30,2.5,32.5,101,TRUE,1,10,Dine-In,Credit Card,2"
        },
        "Menu": {
            "example_headers": "Menu Item,Ingredient,Amount,Unit Cost,Created At,Category,Item Price,Is Active",
            "sample_row": "Pizza,Flour,0.5,2.5,20/10/2025,Entree,18,TRUE"
        }
    }
    return examples.get(category, {})

def get_column_requirements(category: str) -> Dict:
    """
    Get the column requirements for a specific category.
    Useful for API documentation or frontend display.
    """
    if category not in MINIMUM_REQUIRED_COLUMNS:
        return {
            "error": f"Invalid category. Must be one of: {', '.join(MINIMUM_REQUIRED_COLUMNS.keys())}"
        }
    
    requirements = MINIMUM_REQUIRED_COLUMNS[category]
    
    return {
        "category": category,
        "required_columns": requirements["required"],
        "at_least_one_groups": requirements.get("at_least_one", []),
        "recommended_columns": requirements.get("recommended", []),
        "example": get_example_columns(category),
        "description": get_category_description(category)
    }

def get_category_description(category: str) -> str:
    """Get description of what data the category should contain"""
    descriptions = {
        "Labor": "Employee work hours, wages, and scheduling data",
        "Inventory": "Ingredient quantities, costs, and stock levels",
        "Sales": "Transaction data, revenue, and order information",
        "Menu": "Menu items, prices, costs, and descriptions"
    }
    return descriptions.get(category, "")