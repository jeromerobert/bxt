Stuff I cannot find in aws-cli that boto3 can do.


```
usage: bxt updatedns [-h] [-a ACTION] [--ip IP] [-s] zoneid hostname

Update a A DNS record in Route53 possibly synchronously.

positional arguments:
  zoneid                A Route53 Zone ID
  hostname              The hostname to set

optional arguments:
  -h, --help            show this help message and exit
  -a ACTION, --action ACTION
                        <CREATE|DELETE|UPSERT>. Default is UPSERT
  --ip IP               The IP to set. The default is to use the public IP of
                        the current instance.
  -s, --synchronous     Wait until the change have propagated to all Amazon
                        Route 53 DNS servers.
```

or 

```python
import bxt
bxt.update_dns('ZXXXXXXXXXXXXX', 'foo.example.com')
```
