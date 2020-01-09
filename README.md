Stuff I cannot find in aws-cli that boto3 can do, like managing a MPI cluster.

# Install

You would probably do something like:

```
virtualenv -p python3 bxt
. bxt/bin/activate
pip install https://github.com/jeromerobert/bxt/archive/master.zip
```

# Usage

```
usage: bxt.py [-h] {sub,np,rank,hosts,nfs,blkdev,poweroff,updatedns} ...

positional arguments:
  {sub,np,rank,hosts,nfs,blkdev,poweroff,updatedns}
    sub                 Submit a new job.
    np                  Print the number of nodes in the cluster.
    rank                Print the rank of this node in the cluster.
    hosts               Print the comma separated list of nodes in this
                        cluster.
    nfs                 Export NFS from the master node and mount on other
                        nodes.
    blkdev              List unmounted/unpartitionned block devices.
    poweroff            Power off the cluster.
    updatedns           Update a A DNS record in Route53 possibly
                        synchronously.

optional arguments:
  -h, --help            show this help message and exit
```

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
