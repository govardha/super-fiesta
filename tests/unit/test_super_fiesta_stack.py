import aws_cdk as core
import aws_cdk.assertions as assertions

from super_fiesta.super_fiesta_stack import SuperFiestaStack

# example tests. To run these tests, uncomment this file along with the example
# resource in super_fiesta/super_fiesta_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = SuperFiestaStack(app, "super-fiesta")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
