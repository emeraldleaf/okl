namespace OrdersApi;

public record Order(int Id, string Owner, string Item, int Quantity, decimal UnitPrice);

/// In-memory data: two users, orders that belong to each.
public static class Store
{
    public static readonly Dictionary<string, string> Users = new()
    {
        ["alice"] = "token-alice",
        ["bob"] = "token-bob",
    };

    public static readonly Dictionary<int, Order> Orders = new()
    {
        [1] = new(1, "alice", "widget", 2, 9.99m),
        [2] = new(2, "alice", "gadget", 1, 24.50m),
        [3] = new(3, "bob", "gizmo", 5, 3.25m),
    };

    public static readonly Dictionary<string, decimal> Products = new()
    {
        ["widget"] = 9.99m,
        ["gadget"] = 24.50m,
        ["gizmo"] = 3.25m,
    };
}

public static class Auth
{
    /// Resolve the caller from a bearer-like header. Deliberately simple.
    public static string? CurrentUser(HttpContext ctx)
    {
        var token = ctx.Request.Headers["X-User-Token"].FirstOrDefault();
        return Store.Users.FirstOrDefault(u => u.Value == token).Key;
    }
}
