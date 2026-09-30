// orders-api: a small orders service.
// Two users, a handful of orders, an in-memory store.
using OrdersApi;

var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

app.MapGet("/health", () => Results.Ok(new { ok = true }));

// The caller's own orders only.
app.MapGet("/orders", (HttpContext ctx) =>
{
    var user = Auth.CurrentUser(ctx);
    if (user is null) return Results.Unauthorized();
    return Results.Ok(Store.Orders.Values.Where(o => o.Owner == user));
});

app.Run();

public partial class Program { }
