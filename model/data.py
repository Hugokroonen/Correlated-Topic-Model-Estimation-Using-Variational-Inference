"""
Description:
    Contains the Data structure for the CTM model.

Functions:
    create_dataset: creates a dataset for the CTM model using
    the (y_fused_ibn, x, h)-data as input.
"""

# Standard library modules
from collections import namedtuple

# External modules
import numpy as np


Data = namedtuple(
    'Data',
    (
        # data
        'y',
        'x',
        'h',
        'x_outer',
        'x_outer_sum_first',
        'x_outer_sum_not_first',
        'h_outer',
        'h_outer_sum_first',
        'h_outer_sum_not_first',
        'h_per_basket',
        # dimensions
        'dim_j',
        'dim_x',
        'dim_h',
        'dim_i',
        'dim_b',
        'dim_b_min_1',
        'dim_n',
        # counts
        'n_per_customer',
        'n_per_product',
        'total_customers',
        'total_baskets',
        'total_purchases',
        # maps from i->ib and from ib->ibn
        'i_to_ib_lb',
        'i_to_ib_ub',
        'ib_to_ibn_lb',
        'ib_to_ibn_ub',
        # indicators
        'ib_first',
        'ib_not_first',
        'ib_last',
        'ib_not_last',
    )
)


def create_dataset(
        emulate_lda_x, # boolean, set to true if we collapse to LDA-X
        y_fused_ibn,
        x,
        h,
):

    # Get the (i, ib, y_ibn) vectors from the purchase data
    i_vec = np.copy(y_fused_ibn[:, 0]) # customer IDs
    ib_vec = np.copy(y_fused_ibn[:, 1]) # basket IDs  
    y = np.copy(y_fused_ibn[:, 2]) # Product IDs

    if emulate_lda_x:
        # Set basket IDs to customer IDs, collapse to LDA-X
        ib_vec[:] = np.copy(i_vec)
        x = np.zeros((len(np.unique(ib_vec)), 1)) # Create an empty x vector, no trip-specific variables 

    # Assert that the customer ID's and basket ID's are sorted in ascendingo order
    assert np.all(i_vec[1:] - i_vec[:-1] >= 0) 
    assert np.all(ib_vec[1:] - ib_vec[:-1] >= 0) # baskets per customer should be chronologically sorted 

    # Various dimensions
    total_customers = len(np.unique(i_vec)) 
    total_baskets = len(np.unique(ib_vec))
    total_purchases = len(y)

    dim_i = total_customers
    dim_j = len(np.unique(y)) # unique products 
    dim_x = x.shape[1] # number of columns of x vector 
    dim_h = h.shape[1] # number of columns of h vector 

    # Assert that customer, basket, and product IDs are contiguous (no missing or duplicate values)
    assert np.all(np.isin(np.arange(dim_i), i_vec)) 
    assert np.all(np.isin(np.arange(total_baskets), ib_vec))
    assert np.all(np.isin(np.arange(dim_j), y))

    # n_per_product. Calculate the number of purchases per product
    n_per_product = np.zeros(dim_j, dtype=int)
    for y_ibn in y:
        n_per_product[y_ibn] += 1

    # n_per_customer. Calculcating number of purchases per customer.  
    # lb, ub arrays are computed to determine the lower and upper bounds of purchase indices for each customer. 
    # these arrays help in calculating the number of purchases per customer.
    i_to_ibn_lb = np.zeros(total_customers, dtype=int)
    i_to_ibn_ub = np.zeros(total_customers, dtype=int)

    previous_i = i_vec[0]
    for ibn, i in enumerate(i_vec):
        if i != previous_i:
            i_to_ibn_ub[previous_i] = ibn
            i_to_ibn_lb[i] = ibn
            previous_i = i

    i_to_ibn_ub[-1] = total_purchases

    n_per_customer = i_to_ibn_ub - i_to_ibn_lb # number of purchases of each customer 

    # dim_b, dim_b_min_1. Amount of products per basket of a customer. 
    dim_b = np.zeros(total_customers, dtype=int)

    for i in range(total_customers):
        dim_b[i] = len(np.unique(ib_vec[i_to_ibn_lb[i]:i_to_ibn_ub[i]]))

    dim_b_min_1 = dim_b.astype(float) - 1.0

    # ib_to_ibn_lb, ib_to_ibn_ub, n_per_basket, dim_n
    # Calculate the lower and upper bounds of purchase indices for each basket
    ib_to_ibn_lb = np.zeros(total_baskets, dtype=int)
    ib_to_ibn_ub = np.zeros(total_baskets, dtype=int)

    previous_ib = ib_vec[0]
    for ibn, ib in enumerate(ib_vec):
        if ib != previous_ib:
            ib_to_ibn_ub[previous_ib] = ibn
            ib_to_ibn_lb[ib] = ibn
            previous_ib = ib

    ib_to_ibn_ub[-1] = total_purchases

    dim_n = (ib_to_ibn_ub - ib_to_ibn_lb).astype(dtype=float)

    # Sort the purchases per basket
    for ib in range(total_baskets):
        y[ib_to_ibn_lb[ib]:ib_to_ibn_ub[ib]] = np.sort(
            y[ib_to_ibn_lb[ib]:ib_to_ibn_ub[ib]]
        )

    # i_to_ib_lb, i_to_ib_ub
    i_to_ib_lb = np.zeros(total_customers, dtype=int)
    i_to_ib_lb[0] = 0
    i_to_ib_lb[1:] = np.cumsum(dim_b)[:-1]
    i_to_ib_ub = np.cumsum(dim_b)

    # ib_first, ib_not_first, ib_last, ib_not_last
    # Calculate indicators for first and last baskets
    ib_first = np.zeros(total_baskets, dtype=bool) 
    ib_not_first = np.zeros(total_baskets, dtype=bool) 

    ib_last = np.zeros(total_baskets, dtype=bool)
    ib_not_last = np.zeros(total_baskets, dtype=bool)

    ib = 0
    for i in range(dim_i):
        for b in range(dim_b[i]):
            if b == 0:
                ib_first[ib] = True # ib_first are the first baskets 
                ib_not_first[ib] = False
            else:
                ib_first[ib] = False
                ib_not_first[ib] = True # ib_not_first are all not first baskets 

            if b == (dim_b[i] - 1):
                ib_last[ib] = True # ib_last are all last baskets 
                ib_not_last[ib] = False 
            else:
                ib_last[ib] = False 
                ib_not_last[ib] = True # ib_not_last are all not last baskets 
            ib += 1

    # x_outer, x_outer_sum_first, x_outer_sum_not_first (baskets)
    x_outer = np.zeros((total_baskets, dim_x, dim_x))
    for ib in range(total_baskets):
        x_outer[ib] = np.outer(x[ib], x[ib])
    x_outer_sum_first = np.sum(x_outer[ib_first], axis=0) 
    x_outer_sum_not_first = np.sum(x_outer[ib_not_first], axis=0)

    # h_outer, h_outer_sum_first, h_outer_sum_not_first (baskets)
    h_outer = np.zeros((total_customers, dim_h, dim_h))
    for i in range(total_customers):
        h_outer[i] = np.outer(h[i], h[i])
    h_outer_sum_first = np.sum(h_outer, axis=0)
    h_outer_sum_not_first = np.sum(
        h_outer * (dim_b[:, np.newaxis, np.newaxis] - 1.0),
        axis=0,
    )

    # Create the h_per_basket matrix to relate customer-specific variables to each basket
    h_per_basket = np.zeros((total_baskets, dim_h))
    ib = 0
    for i in range(total_customers):
        for b in range(dim_b[i]):
            h_per_basket[ib] = h[i]
            ib += 1

    # Emulate LDA-X specific conditions
    if emulate_lda_x:
        assert x.shape == (total_customers, 1) # assures x has total_customers rows and 1 column 
        assert np.allclose(x, 0.0) # ensures all x values are close to zero, meaning no trip-specific variables 
        assert total_customers == total_baskets # each customer only has one basket, as in LDA-X
        assert np.all(i_vec == ib_vec) # verifies that each basket is associated with its corresponding customer

    data = Data(
        # data
        y=y,
        x=x,
        h=h,
        x_outer=x_outer,
        x_outer_sum_first=x_outer_sum_first,
        x_outer_sum_not_first=x_outer_sum_not_first,
        h_outer=h_outer,
        h_outer_sum_first=h_outer_sum_first,
        h_outer_sum_not_first=h_outer_sum_not_first,
        h_per_basket=h_per_basket,
        # dimensions
        dim_j=dim_j,
        dim_x=dim_x,
        dim_h=dim_h,
        dim_i=dim_i,
        dim_b=dim_b,
        dim_b_min_1=dim_b_min_1,
        dim_n=dim_n,
        # counts
        n_per_customer=n_per_customer,
        n_per_product=n_per_product,
        total_customers=total_customers,
        total_baskets=total_baskets,
        total_purchases=total_purchases,
        # maps from i->ib and from ib->ibn
        i_to_ib_lb=i_to_ib_lb,
        i_to_ib_ub=i_to_ib_ub,
        ib_to_ibn_lb=ib_to_ibn_lb,
        ib_to_ibn_ub=ib_to_ibn_ub,
        # indicators
        ib_first=ib_first,
        ib_not_first=ib_not_first,
        ib_last=ib_last,
        ib_not_last=ib_not_last,
    )

    return data