- dont allow modifying dns records unless create resources is true DONE
- add the ability to deploy to a specific ec2 instance, such that you only have ssh access and nothing else to that instance (dev servers)

btw, the vercel one is totally untested


also todo: make it so you can add a clooudflare api key and it will then search cloudflare for a domain and wire it all up

todo: add the ability to deploy to an s3 bucket. this will be domain updating (same as standard aws) -> cloudfront (same as standard s3 deployment, but cache but 10 min) -> s3 bucket. instead of using a docker file it points to a folder. there should be an index.html file in that folder (and throw an error if there isn't)


remove all the config by args, it has to be controlled by a config file  DONE